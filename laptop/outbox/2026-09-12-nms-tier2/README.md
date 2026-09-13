# NMS Tier 2 input

This folder contains Bruce's current longest-played logical Slot Three pair for
Tier 2 development. The raw save data is not public: the four files are packaged
in `nms-slot3-auto-manual.zip.aesgcm` using AES-256-GCM.

Contents after decryption:

- `save5.hg` and `mf_save5.hg` — automatic restore state and metadata
- `save6.hg` and `mf_save6.hg` — manual restore state and metadata

Medic receives the one-time `MEDIC_NMS_TIER2_KEY_B64` value through the private
bridge, not through this public repository. With Python `cryptography` installed:

```text
python decrypt_nms_tier2.py nms-slot3-auto-manual.zip.aesgcm nms-slot3-auto-manual.zip
```

The laptop-side source files were copied read-only while No Man's Sky was closed
and were hash-checked before and after packaging.
