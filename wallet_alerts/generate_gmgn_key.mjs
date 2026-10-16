// Ed25519/SPKI/PKCS8 match gmgn-cli 1.6.6 config generation exactly.
// Store secrets in the writable tools directory; never print private material.
import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

const dir = process.argv[2] || '/workspace/gmgn-tools/auth';
const privateFile = path.join(dir, 'ed25519-private.pem');
const publicFile = path.join(dir, 'ed25519-public.pem');
if (!fs.existsSync(privateFile) && (fs.existsSync(publicFile) || process.env.GMGN_API_KEY)) {
  throw new Error('Existing registration or public key found but private key is missing. Do not replace it automatically.');
}
fs.mkdirSync(dir, {recursive:true, mode:0o700});
let privateKey;
if (fs.existsSync(privateFile)) {
  privateKey = crypto.createPrivateKey(fs.readFileSync(privateFile));
  if (privateKey.asymmetricKeyType !== 'ed25519') throw new Error('Unexpected key type');
} else {
  privateKey = crypto.generateKeyPairSync('ed25519').privateKey;
  fs.writeFileSync(privateFile, privateKey.export({type:'pkcs8',format:'pem'}), {mode:0o600,flag:'wx'});
}
const publicKey = crypto.createPublicKey(privateKey);
const publicPem = publicKey.export({type:'spki',format:'pem'});
if (fs.existsSync(publicFile)) {
  if (fs.readFileSync(publicFile,'utf8') !== publicPem) throw new Error('Public/private key mismatch');
} else fs.writeFileSync(publicFile, publicPem, {mode:0o644,flag:'wx'});
const message = Buffer.from('GMGN read-only integration self-test');
if (!crypto.verify(null,message,publicKey,crypto.sign(null,message,privateKey))) {
  throw new Error('Keypair signature verification failed');
}
console.log(publicPem.trim());
console.log('Create URL: https://gmgn.ai/ai/generateapi?pbk='+encodeURIComponent(publicPem));
console.log('Private key remains local; signature self-test passed.');
