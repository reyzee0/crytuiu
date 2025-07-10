import base58
import json

# Paste your private key here
key_base58 = "4uei6YuVhj6nN9SpLiEkZh6a9M9zNJtxnLgVJ3kEGbZucozrfMszt48fwCajgeugdJYWCVKX9zTA2Dehj6dnjSDW"

# Decode base58
key_bytes = base58.b58decode(key_base58)

# Convert to list of ints
key_list = list(key_bytes)
print(key_list)

# Save to phantom_keypair.json
with open("phantom_keypair.json", "w") as f:
    json.dump(key_list, f)
print("phantom_keypair.json saved. Ready to use.")
