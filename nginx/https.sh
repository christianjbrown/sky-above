#!/bin/sh
# Run by the nginx image before nginx starts. Switches the https server on once
# the certs service has a certificate, then checks every few hours so a new or
# renewed certificate is picked up without a restart.
set -eu

https_on() {
    if [ -n "${CERT_DOMAIN:-}" ] && [ -f "/certs/certificates/${CERT_DOMAIN}.crt" ]; then
        cp /etc/nginx/https.conf /etc/nginx/conf.d/https.conf
    fi
}

https_on
(
    while sleep 21600; do
        https_on
        nginx -s reload || true
    done
) &
