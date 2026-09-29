package com.bet365agent;

import android.util.Log;
import java.io.*;
import java.net.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.charset.CodingErrorAction;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;

/** Small bounded HTTP/1.1 transport. No public/wildcard binding, proxying, CORS or chunked bodies. */
final class CoordinatorHttp implements AutoCloseable {
    static final class Reply {
        final int code; final String type; final byte[] data; Runnable afterWrite;
        Reply(int code, String type, byte[] data) { this.code = code; this.type = type; this.data = data; }
    }
    /** LAN (wlan/eth RFC1918) and/or Tailscale tun CGNAT bind targets. Never rmnet/public/wildcard. */
    private static final class BindTargets {
        final InetAddress lan;
        final InetAddress tailscale;
        BindTargets(InetAddress lan, InetAddress tailscale) { this.lan = lan; this.tailscale = tailscale; }
        boolean empty() { return lan == null && tailscale == null; }
        @Override public boolean equals(Object o) {
            if (!(o instanceof BindTargets)) return false;
            BindTargets other = (BindTargets) o;
            return Objects.equals(lan, other.lan) && Objects.equals(tailscale, other.tailscale);
        }
        @Override public int hashCode() { return Objects.hash(lan, tailscale); }
        List<InetAddress> addresses() {
            List<InetAddress> list = new ArrayList<>(2);
            if (lan != null) list.add(lan);
            if (tailscale != null) list.add(tailscale);
            return list;
        }
        /** Clean primary URL for clients/fixture open. Prefer Tailscale when dual-bound; never annotate here. */
        String endpointLabel(int port) {
            InetAddress primary = tailscale != null ? tailscale : lan;
            return primary == null ? null : "http://" + primary.getHostAddress() + ":" + port;
        }
        String listenDetail(int port) {
            if (tailscale != null && lan != null)
                return endpointLabel(port) + " (+lan http://" + lan.getHostAddress() + ":" + port + ")";
            return endpointLabel(port);
        }
    }
    private final CoordinatorAgent agent;
    private final ScheduledExecutorService deadlines = Executors.newSingleThreadScheduledExecutor();
    private final ThreadPoolExecutor clients = new ThreadPoolExecutor(4, 4, 0, TimeUnit.SECONDS, new ArrayBlockingQueue<>(12));
    private volatile boolean closed;
    private volatile List<ServerSocket> servers = Collections.emptyList();
    private volatile String endpoint;
    private final Thread listener;

    CoordinatorHttp(CoordinatorAgent agent) {
        this.agent = agent;
        listener = new Thread(this::listen, "coordinator-http"); listener.start();
    }
    String endpoint() { return endpoint; }
    /** RFC1918 LAN or Tailscale CGNAT (100.64.0.0/10). Used for trusted peer checks. */
    static boolean privateAddress(InetAddress address) {
        if (!(address instanceof Inet4Address)) return false;
        byte[] b = address.getAddress(); int a = b[0] & 255, second = b[1] & 255;
        return a == 10 || (a == 172 && second >= 16 && second <= 31) || (a == 192 && second == 168)
            || (a == 100 && second >= 64 && second <= 127);
    }
    static boolean tailscaleAddress(InetAddress address) {
        if (!(address instanceof Inet4Address)) return false;
        byte[] b = address.getAddress(); int a = b[0] & 255, second = b[1] & 255;
        return a == 100 && second >= 64 && second <= 127;
    }
    private static BindTargets discoverAddresses() throws Exception {
        // Dual-bind when both Wi-Fi/Ethernet RFC1918 and Tailscale tun CGNAT exist.
        // Never bind carrier/mobile (rmnet) or wildcard/public addresses.
        InetAddress lan = null, tailscale = null;
        for (NetworkInterface nic : Collections.list(NetworkInterface.getNetworkInterfaces())) {
            if (!nic.isUp()) continue;
            String name = nic.getName();
            boolean wifiEth = name.startsWith("wlan") || name.startsWith("eth");
            boolean tun = name.startsWith("tun");
            if (!wifiEth && !tun) continue;
            for (InetAddress address : Collections.list(nic.getInetAddresses())) {
                if (wifiEth && privateAddress(address) && !tailscaleAddress(address) && lan == null) lan = address;
                if (tun && tailscaleAddress(address) && tailscale == null) tailscale = address;
            }
        }
        return new BindTargets(lan, tailscale);
    }
    private static ServerSocket bindOne(InetAddress address) throws IOException {
        ServerSocket socket = new ServerSocket();
        socket.setReuseAddress(true);
        socket.bind(new InetSocketAddress(address, CoordinatorConfig.PORT), 12);
        socket.setSoTimeout(500);
        return socket;
    }
    private void listen() {
        while (!closed) {
            List<ServerSocket> open = new ArrayList<>(2);
            try {
                BindTargets targets = discoverAddresses();
                if (targets.empty()) { Thread.sleep(1500); continue; }
                for (InetAddress address : targets.addresses()) open.add(bindOne(address));
                servers = Collections.unmodifiableList(new ArrayList<>(open));
                endpoint = targets.endpointLabel(CoordinatorConfig.PORT);
                Log.i("AgentCoordinator", "LISTEN " + targets.listenDetail(CoordinatorConfig.PORT));
                // One acceptor per bound socket. A single loop taking turns over the LAN and the Tailscale socket, each
                // accept() blocking up to its 500 ms timeout, made a request on the second socket wait for the first
                // socket's timeout: a median of ~0.5 s (up to 1 s) on EVERY call the backend makes over Tailscale (job
                // ACK, health, result polls). The address supervision below runs on this thread; a change closes the
                // sockets (finally), which ends the acceptors.
                for (ServerSocket socket : open) {
                    Thread acceptor = new Thread(() -> accept(socket), "coordinator-accept-" + socket.getLocalPort());
                    acceptor.setDaemon(true);
                    acceptor.start();
                }
                while (!closed && targets.equals(discoverAddresses())) Thread.sleep(500);
            } catch (Exception e) {
                if (!closed) Log.w("AgentCoordinator", "Listener retry: " + e.getClass().getSimpleName());
                try { Thread.sleep(1000); } catch (InterruptedException ignored) { }
            } finally {
                endpoint = null; servers = Collections.emptyList();
                for (ServerSocket socket : open) {
                    try { socket.close(); } catch (IOException ignored) { }
                }
            }
        }
    }
    /** Accept loop of ONE server socket: hand each private-address peer to the bounded client pool. */
    private void accept(ServerSocket socket) {
        while (!closed && !socket.isClosed()) {
            try {
                Socket client = socket.accept();
                if (!privateAddress(client.getInetAddress())) { client.close(); continue; }
                try { clients.execute(() -> handle(client)); }
                catch (RejectedExecutionException busy) { client.close(); }
            } catch (SocketTimeoutException ignored) {
            } catch (IOException closedOrFailed) {
                return;   // the supervisor closed this socket (address change / shutdown)
            }
        }
    }

    private void handle(Socket socket) {
        Reply reply = null;
        ScheduledFuture<?> deadline = deadlines.schedule(() -> { try { socket.close(); } catch (IOException ignored) { } }, 5, TimeUnit.SECONDS);
        try (Socket client = socket) {
            client.setSoTimeout(3000);
            client.setTcpNoDelay(true);   // small replies: never wait for Nagle/delayed-ACK
            try {
                InputStream in = client.getInputStream();
                String[] start = line(in, 1024).split(" ");
                if (start.length != 3 || !start[2].equals("HTTP/1.1") || !start[1].startsWith("/")) throw new IOException("Invalid request line");
                Map<String, String> headers = new HashMap<>(); int size = 0;
                for (;;) {
                    String line = line(in, 2048); size += line.length() + 2;
                    if (size > 8192) throw new IOException("Headers too large");
                    if (line.isEmpty()) break;
                    int colon = line.indexOf(':');
                    if (colon <= 0 || Character.isWhitespace(line.charAt(0))) throw new IOException("Invalid header");
                    String key = line.substring(0, colon).toLowerCase(Locale.US);
                    if (headers.put(key, line.substring(colon + 1).trim()) != null) throw new IOException("Duplicate header");
                }
                if (headers.containsKey("transfer-encoding") || headers.containsKey("expect")) throw new IOException("Unsupported framing");
                String rawLength = headers.getOrDefault("content-length", "0");
                if (!rawLength.matches("[0-9]{1,5}")) throw new IOException("Invalid Content-Length");
                int length = Integer.parseInt(rawLength);
                if (length > 4096 || (!start[0].equals("POST") && length != 0)) throw new IOException("Invalid body size");
                boolean fixture = start[0].equals("GET") && Set.of("/neutral/text.html", "/neutral/simulator.html").contains(start[1].split("\\?", 2)[0]);
                String provided = headers.getOrDefault("authorization", "");
                boolean authorized = MessageDigest.isEqual(("Bearer " + agent.token()).getBytes(StandardCharsets.UTF_8), provided.getBytes(StandardCharsets.UTF_8));
                if (!fixture && !authorized) reply = agent.error(401, "", "INVALID_INSTRUCTION", "Authentication required");
                else if (!fixture && headers.containsKey("origin")) reply = agent.error(403, "", "INVALID_INSTRUCTION", "Browser-origin API requests are not accepted");
                else {
                    if (start[0].equals("POST") && !headers.getOrDefault("content-type", "").split(";", 2)[0].trim().equalsIgnoreCase("application/json")) throw new IOException("application/json required");
                    byte[] body = new byte[length]; int offset = 0;
                    while (offset < length) { int read = in.read(body, offset, length - offset); if (read < 0) throw new EOFException(); offset += read; }
                    String json = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(body)).toString();
                    reply = agent.route(start[0], start[1], json);
                }
            } catch (SocketTimeoutException | EOFException incomplete) {
                // Chrome preconnects idle sockets. Close them silently; never leave a stale 400 for its next navigation.
                return;
            } catch (Exception e) {
                Log.w("AgentCoordinator", "Request rejected: " + e.getClass().getSimpleName() + ": " + e.getMessage());
                reply = agent.error(400, "", "INVALID_INSTRUCTION", "Malformed or incomplete HTTP/JSON request");
            }
            try {
                OutputStream out = client.getOutputStream();
                String header = "HTTP/1.1 " + reply.code + " Response\r\nContent-Type: " + reply.type
                    + "\r\nContent-Length: " + reply.data.length + "\r\nConnection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n\r\n";
                byte[] head = header.getBytes(StandardCharsets.US_ASCII);
                byte[] whole = new byte[head.length + reply.data.length];      // one write: header and body leave together
                System.arraycopy(head, 0, whole, 0, head.length);
                System.arraycopy(reply.data, 0, whole, head.length, reply.data.length);
                out.write(whole); out.flush();
            } finally {
                // A lost ACK never rolls back an accepted instruction or causes a second dispatch.
                if (reply.afterWrite != null) reply.afterWrite.run();
            }
        } catch (Exception ignored) { /* disconnected or timed-out client; ledger remains authoritative */ }
        finally { deadline.cancel(false); }
    }
    private static String line(InputStream in, int limit) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        while (bytes.size() <= limit) {
            int b = in.read(); if (b < 0) throw new EOFException();
            if (b == '\n') {
                byte[] line = bytes.toByteArray();
                if (line.length == 0 || line[line.length - 1] != '\r') throw new IOException("CRLF required");
                return new String(line, 0, line.length - 1, StandardCharsets.US_ASCII);
            }
            bytes.write(b);
        }
        throw new IOException("Line too long");
    }
    @Override public void close() {
        closed = true; endpoint = null;
        for (ServerSocket socket : servers) {
            try { socket.close(); } catch (IOException ignored) { }
        }
        listener.interrupt(); clients.shutdownNow(); deadlines.shutdownNow();
    }
}