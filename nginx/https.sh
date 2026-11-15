#!/bin/sh
# Run by the nginx image before nginx starts. Switches the https server on once
# the certs service has a certificate, and each of OTHER_SITES once it has that
# name's, sends each of those names from plain http to https, then checks every
# few hours so a new or renewed certificate is picked up without a restart.
set -eu

https_on() {
    if [ -n "${CERT_DOMAIN:-}" ] && [ -f "/certs/certificates/${CERT_DOMAIN}.crt" ]; then
        cp /etc/nginx/https.conf /etc/nginx/conf.d/https.conf
    fi
    other_sites > /etc/nginx/conf.d/other-sites.conf
    to_https > /etc/nginx/conf.d/to-https.conf
}

# The names that have their certificate: CERT_DOMAIN and each of OTHER_SITES.
secured() {
    if [ -n "${CERT_DOMAIN:-}" ] && [ -f "/certs/certificates/${CERT_DOMAIN}.crt" ]; then
        echo "$CERT_DOMAIN"
    fi
    for site in ${OTHER_SITES:-}; do
        name=${site%%=*}
        case "$name" in "" | *[!a-z0-9.-]*) continue ;; esac
        if [ -f "/certs/certificates/$name.crt" ]; then
            echo "$name"
        fi
    done
}

# Plain http for any of those names, on HTTP_PORT, goes to the same address over https.
# Anything else there, such as the Pi's own address, gets the card as on RECEIVER_PORT.
to_https() {
    names=$(secured | tr '\n' ' ')
    if [ -n "${names% }" ]; then
        sed "s/@NAMES@/${names% }/" /etc/nginx/to-https.conf.in
    fi
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
