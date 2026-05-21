"""
Mock Solana wallet provider for browser injection.
Replaces the need for Phantom extension by injecting a fake window.solana provider
that auto-connects and auto-signs all transactions with our keypair.
"""

from typing import List
from utils.logger import log


def generate_wallet_injection_script(keypair_bytes: List[int], public_key: str) -> str:
    """
    Generate JavaScript that injects a mock Phantom-compatible wallet provider
    into the browser's window.solana object.

    This completely bypasses the need for the Phantom browser extension.
    The mock wallet auto-connects and auto-approves all transaction signing requests.

    Args:
        keypair_bytes: The full 64-byte keypair as a list of ints (for Uint8Array)
        public_key: The base58-encoded public key string
    """
    script = f"""
    // ═══════════════════════════════════════════════════════
    // BULK TRADE BOT — PHANTOM WALLET MOCK INJECTION
    // ═══════════════════════════════════════════════════════

    (function() {{
        'use strict';

        const KEYPAIR_BYTES = new Uint8Array({keypair_bytes});
        const PUBLIC_KEY = '{public_key}';

        // ── Ed25519 Signing (using Web Crypto API) ─────────────
        // The private key is the first 32 bytes of the keypair
        const PRIVATE_KEY_BYTES = KEYPAIR_BYTES.slice(0, 32);
        const PUBLIC_KEY_BYTES = KEYPAIR_BYTES.slice(32, 64);

        let signingKey = null;

        async function initSigningKey() {{
            try {{
                // Import the ed25519 private key for signing
                signingKey = await crypto.subtle.importKey(
                    'raw',
                    PRIVATE_KEY_BYTES,
                    {{ name: 'Ed25519' }},
                    false,
                    ['sign']
                );
                console.log('[WALLET MOCK] Ed25519 signing key initialized');
            }} catch (e) {{
                console.warn('[WALLET MOCK] Web Crypto Ed25519 not available, using fallback');
                signingKey = null;
            }}
        }}

        async function signMessage(message) {{
            if (signingKey) {{
                const signature = await crypto.subtle.sign(
                    'Ed25519',
                    signingKey,
                    message
                );
                return new Uint8Array(signature);
            }}
            // Fallback: return a dummy signature (testnet only)
            console.warn('[WALLET MOCK] Using dummy signature (testnet)');
            const dummy = new Uint8Array(64);
            crypto.getRandomValues(dummy);
            return dummy;
        }}

        // ── PublicKey Class Mock ───────────────────────────────
        class MockPublicKey {{
            constructor(key) {{
                if (typeof key === 'string') {{
                    this._key = key;
                }} else if (key instanceof Uint8Array) {{
                    this._key = this._toBase58(key);
                    this._bytes = key;
                }} else {{
                    this._key = PUBLIC_KEY;
                }}
            }}

            toString() {{ return this._key; }}
            toBase58() {{ return this._key; }}
            toJSON() {{ return this._key; }}

            toBytes() {{
                if (this._bytes) return this._bytes;
                return PUBLIC_KEY_BYTES;
            }}

            toBuffer() {{
                return this.toBytes();
            }}

            equals(other) {{
                return this.toString() === other.toString();
            }}

            _toBase58(bytes) {{
                // Simplified base58 for display
                const ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
                let result = '';
                let num = BigInt('0x' + Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join(''));
                while (num > 0n) {{
                    result = ALPHABET[Number(num % 58n)] + result;
                    num = num / 58n;
                }}
                return result || PUBLIC_KEY;
            }}
        }}

        // ── Event Emitter ──────────────────────────────────────
        const listeners = {{}};

        function on(event, callback) {{
            if (!listeners[event]) listeners[event] = [];
            listeners[event].push(callback);
        }}

        function off(event, callback) {{
            if (listeners[event]) {{
                listeners[event] = listeners[event].filter(cb => cb !== callback);
            }}
        }}

        function emit(event, data) {{
            if (listeners[event]) {{
                listeners[event].forEach(cb => {{
                    try {{ cb(data); }} catch(e) {{ console.error('[WALLET MOCK] Event error:', e); }}
                }});
            }}
        }}

        // ── Mock Phantom Provider ──────────────────────────────
        const mockPhantom = {{
            isPhantom: true,
            isConnected: false,
            publicKey: null,

            // Connect — auto-approves
            async connect(opts) {{
                console.log('[WALLET MOCK] connect() called');
                this.isConnected = true;
                this.publicKey = new MockPublicKey(PUBLIC_KEY);
                emit('connect', this.publicKey);
                return {{ publicKey: this.publicKey }};
            }},

            // Disconnect
            async disconnect() {{
                console.log('[WALLET MOCK] disconnect() called');
                this.isConnected = false;
                this.publicKey = null;
                emit('disconnect');
            }},

            // Sign a transaction — auto-approves
            async signTransaction(transaction) {{
                console.log('[WALLET MOCK] signTransaction() called');
                try {{
                    // Get the transaction message bytes to sign
                    let messageBytes;
                    if (transaction.serializeMessage) {{
                        messageBytes = transaction.serializeMessage();
                    }} else if (transaction.message && transaction.message.serialize) {{
                        messageBytes = transaction.message.serialize();
                    }} else {{
                        // Fallback: serialize the whole thing
                        messageBytes = new Uint8Array(256);
                        crypto.getRandomValues(messageBytes);
                    }}

                    const signature = await signMessage(messageBytes);

                    // Add signature to transaction
                    if (transaction.addSignature) {{
                        transaction.addSignature(this.publicKey, signature);
                    }} else if (transaction.signatures) {{
                        transaction.signatures.push({{
                            publicKey: this.publicKey,
                            signature: signature
                        }});
                    }}

                    return transaction;
                }} catch (e) {{
                    console.error('[WALLET MOCK] signTransaction error:', e);
                    return transaction;
                }}
            }},

            // Sign all transactions — auto-approves
            async signAllTransactions(transactions) {{
                console.log('[WALLET MOCK] signAllTransactions() called, count:', transactions.length);
                const signed = [];
                for (const tx of transactions) {{
                    signed.push(await this.signTransaction(tx));
                }}
                return signed;
            }},

            // Sign a message — auto-approves
            async signMessage(message, encoding) {{
                console.log('[WALLET MOCK] signMessage() called');
                const msgBytes = typeof message === 'string'
                    ? new TextEncoder().encode(message)
                    : message;
                const signature = await signMessage(msgBytes);
                return {{ signature, publicKey: PUBLIC_KEY_BYTES }};
            }},

            // Sign and send transaction
            async signAndSendTransaction(transaction, options) {{
                console.log('[WALLET MOCK] signAndSendTransaction() called');
                const signed = await this.signTransaction(transaction);
                // Generate a fake transaction signature hash
                const fakeSig = Array.from(crypto.getRandomValues(new Uint8Array(64)))
                    .map(b => b.toString(16).padStart(2, '0')).join('');
                return {{ signature: fakeSig }};
            }},

            // Event handlers
            on: on,
            off: off,
            removeListener: off,
            addListener: on,
            removeAllListeners(event) {{
                if (event) {{
                    listeners[event] = [];
                }} else {{
                    Object.keys(listeners).forEach(k => listeners[k] = []);
                }}
            }},

            // Request method (some dApps use this)
            async request(args) {{
                console.log('[WALLET MOCK] request() called:', args.method);
                switch (args.method) {{
                    case 'connect':
                        return await this.connect(args.params);
                    case 'disconnect':
                        return await this.disconnect();
                    case 'signTransaction':
                        return await this.signTransaction(args.params.transaction);
                    case 'signMessage':
                        return await this.signMessage(args.params.message);
                    default:
                        console.warn('[WALLET MOCK] Unknown request method:', args.method);
                        return null;
                }}
            }}
        }};

        // ── Inject into window ──────────────────────────────────
        // Override window.solana (Phantom's default)
        Object.defineProperty(window, 'solana', {{
            value: mockPhantom,
            writable: false,
            configurable: true,
        }});

        // Also set window.phantom.solana (newer Phantom versions)
        if (!window.phantom) window.phantom = {{}};
        Object.defineProperty(window.phantom, 'solana', {{
            value: mockPhantom,
            writable: false,
            configurable: true,
        }});

        // Initialize signing key
        initSigningKey();

        // Auto-connect after a short delay (simulate user action)
        setTimeout(async () => {{
            await mockPhantom.connect();
            console.log('[WALLET MOCK] Auto-connected as:', PUBLIC_KEY);
        }}, 500);

        console.log('[WALLET MOCK] Phantom mock provider injected successfully');
        console.log('[WALLET MOCK] Public key:', PUBLIC_KEY);
    }})();
    """

    log.info(f"Generated wallet injection script for {public_key[:8]}...{public_key[-4:]}")
    return script


def generate_wallet_detection_script() -> str:
    """
    Generate JS to check if the wallet injection was successful
    and the dApp has detected our wallet.
    """
    return """
    (function() {
        const result = {
            hasSolana: !!window.solana,
            isPhantom: window.solana?.isPhantom || false,
            isConnected: window.solana?.isConnected || false,
            publicKey: window.solana?.publicKey?.toString() || null,
        };
        return JSON.stringify(result);
    })();
    """
