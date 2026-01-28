#!/bin/bash

# Certificate Management
# Checks and setups certificate paths

export USE_CERT=${USE_CERT:-"false"}

if [ "$USE_CERT" = "true" ]; then
    echo "Checking Certificates..."
    
    if [ -n "$DOCUMENTUM_CERT_PATH" ] && [ -f "$DOCUMENTUM_CERT_PATH" ]; then
         echo "Verified Certificate: $DOCUMENTUM_CERT_PATH"
    else
         echo "USE_CERT is true but DOCUMENTUM_CERT_PATH is invalid or missing: $DOCUMENTUM_CERT_PATH"
         # exit 1 # Optional: Fail fast if certs are required
    fi
    
    if [ -n "$DOCUMENTUM_KEY_PATH" ] && [ -f "$DOCUMENTUM_KEY_PATH" ]; then
         echo "Verified Key: $DOCUMENTUM_KEY_PATH"
    else
         echo "USE_CERT is true but DOCUMENTUM_KEY_PATH is invalid or missing: $DOCUMENTUM_KEY_PATH"
         # exit 1
    fi
else
    echo "Certificates invalid or not enabled."
fi
