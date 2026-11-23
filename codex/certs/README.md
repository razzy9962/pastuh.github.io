# Public T-Invest TLS trust anchor

`russian-trusted-root-ca.pem` is a **public CA certificate**, not a private key or secret.

Source (verified HTTPS download): https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt

T-Bank certificate documentation: https://developer.tbank.ru/docs/tls-settings

Subject: `C=RU, O=The Ministry of Digital Development and Communications, CN=Russian Trusted Root CA`

SHA-256 fingerprint: `D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31`

The application validates the fingerprint, certificate chain, and hostname. This extra trust is scoped exclusively to `invest-public-api.tbank.ru` in `src/lib/tinvest-client.ts`; it does not modify system trust or disable HTTPS verification. When rotating the official CA, verify its provenance and update the pinned fingerprint intentionally.
