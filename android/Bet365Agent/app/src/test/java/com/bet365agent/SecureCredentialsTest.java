package com.bet365agent;

import android.content.SharedPreferences;
import java.lang.reflect.Proxy;
import java.util.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class SecureCredentialsTest {
    private SharedPreferences prefs(Map<String,String> data, boolean commit) {
        Map<String,String> pending = new HashMap<>(); Set<String> removed = new HashSet<>();
        SharedPreferences.Editor editor = (SharedPreferences.Editor) Proxy.newProxyInstance(getClass().getClassLoader(), new Class[]{SharedPreferences.Editor.class}, (proxy,m,args) -> {
            if (m.getName().equals("putString")) { pending.put((String)args[0],(String)args[1]); return proxy; }
            if (m.getName().equals("remove")) { removed.add((String)args[0]); return proxy; }
            if (m.getName().equals("commit")) { if(commit){data.putAll(pending);for(String k:removed)data.remove(k);} return commit; }
            return null;
        });
        return (SharedPreferences) Proxy.newProxyInstance(getClass().getClassLoader(), new Class[]{SharedPreferences.class}, (proxy,m,args) -> {
            if(m.getName().equals("contains"))return data.containsKey(args[0]);
            if(m.getName().equals("getString"))return data.getOrDefault(args[0],(String)args[1]);
            if(m.getName().equals("edit"))return editor;
            return null;
        });
    }
    private Map<String,String> legacy() { return new HashMap<>(Map.of("bet365_username","test_account","bet365_password","test_secret")); }
    @Test public void keystoreFailureNeverReturnsLegacyPlaintext() {
        Map<String,String> old = legacy();
        assertNull(SecureCredentials.open(prefs(old,true), ()->{throw new Exception("key unavailable");}));
        assertEquals(2,old.size());assertTrue(SecureCredentials.storeKind().startsWith("unavailable"));
    }
    @Test public void failedEncryptedWritePreservesLegacyAndFailsClosed() {
        Map<String,String> old = legacy();
        assertNull(SecureCredentials.open(prefs(old,true), ()->prefs(new HashMap<>(),false)));
        assertEquals(2,old.size());
    }
    @Test public void mismatchedReadbackNeverDeletesOriginal() {
        Map<String,String> old = legacy();
        assertNull(SecureCredentials.open(prefs(old,true), ()->prefs(new HashMap<>(Map.of("username","wrong","password","wrong")),true)));
        assertEquals(2,old.size());
    }
    @Test public void migrationVerifiesBeforeRemovingPlaintext() {
        Map<String,String> old = legacy(), encrypted = new HashMap<>();
        assertNotNull(SecureCredentials.open(prefs(old,true), ()->prefs(encrypted,true)));
        assertTrue(old.isEmpty());assertEquals("test_secret",encrypted.get("password"));
    }
    @Test public void cleanupFailureDoesNotEnableAuthentication() {
        assertNull(SecureCredentials.open(prefs(legacy(),false), ()->prefs(new HashMap<>(),true)));
    }
}
