package com.bet365agent;

/** A fresh input connection must also belong to Chrome's password editor. */
final class SecretEditor {
    static boolean matches(String packageName, int inputType) {
        int variation = inputType & 0xfff;
        return "com.android.chrome".equals(packageName)
            && (variation == 0x81 || variation == 0x91 || variation == 0xe1 || variation == 0x12);
    }
}
