# E91 / BBM92 Hardware Proof

This repo contains a focused **cryptographic-signaling quantum proof** on IBM Quantum hardware.

- Builds entangled pairs with a Bell-state source.
- Measures four basis combinations required by CHSH.
- Reports:
  - CHSH Bell parameter `S`
  - QBER from matched-basis rounds
  - Strict pass/fail on
    - `S >= 2.15`
    - `QBER <= 0.12`
- Repeats hardware runs for a reproducible aggregate with 95% CI.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 e91_qkd_proof.py --repetitions 3 --shots 2048 --output results/e91_proof_hardware.json
```

## Hardware proof result

The script writes:
- job IDs per run
- per-setting counts (`00`,`01`,`10`,`11`)
- per-run and aggregate `S`, `QBER`, and CI intervals

Current target backend: `ibm_fez`
