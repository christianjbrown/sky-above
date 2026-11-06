#!/bin/sh
# Run by the nginx image before nginx starts. Switches the https server on once
# the certs service has a certificate, and each of OTHER_SITES once it has that
# name's, then checks every few hours so a new or renewed certificate is picked
# up without a restart.
set -eu

https_on() {
    if [ -n "${CERT_DOMAIN:-}" ] && [ -f "/certs/certificates/${CERT_DOMAIN}.crt" ]; then
        cp /etc/nginx/https.conf /etc/nginx/conf.d/https.conf
    fi
    other_sites > /etc/nginx/conf.d/other-sites.conf
}

# A server for each name=port in OTHER_SITES that has its certificate, passing it
# through to that port on the Pi. Anything that is not a plain name and port is
# left out, so a typo cannot stop nginx starting.
other_sites() {
    for site in ${OTHER_SITES:-}; do
        name=${site%%=*}
        port=${site#*=}
        case "$name" in "" | *[!a-z0-9.-]*) echo "# left out $site: not a name=port" ; continue ;; esac
        case "$port" in "" | *[!0-9]*) echo "# left out $site: not a name=port" ; continue ;; esac
        if [ -f "/certs/certificates/$name.crt" ]; then
            sed -e "s/@NAME@/$name/g" -e "s/@PORT@/$port/g" /etc/nginx/other-site.conf.in
        fi
    done
}

https_on
(
    while sleep 21600; do
        https_on
        nginx -s reload || true
    done
) &
