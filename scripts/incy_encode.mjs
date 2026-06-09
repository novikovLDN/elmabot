// Sidecar: encode a subscription URL into an incy://crypt1/ deep link.
// Called by app/services/incy_crypto.py as: node incy_encode.mjs <url>
// Prints the link to stdout, or exits non-zero with a message on stderr.
import { encryptLink } from '@incy/link-encoder';

const url = process.argv[2];
if (!url) {
  process.stderr.write('usage: node incy_encode.mjs <subscription-url>');
  process.exit(1);
}
process.stdout.write(encryptLink(url, { name: 'Elma VPN' }));
