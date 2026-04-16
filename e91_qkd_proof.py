#!/usr/bin/env python3
"""E91 / BBM92-style hardware proof: CHSH violation + QBER.

Strict success criterion:
- CHSH Bell parameter S > CHSH_THRESHOLD
- QBER in matching-basis rounds < QBER_THRESHOLD

The experiment is a 2-qubit entangled-pair protocol with four fixed basis settings.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import numpy as np
from qiskit import QuantumCircuit
from qiskit.transpiler import PassManager
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2


CHSH_THRESHOLD = 2.15
QBER_THRESHOLD = 0.12

# E91 / BBM92 fixed angles in XZ plane: rotate by RY(-theta) then measure Z
# with |Phi+> source state prep: H(0), CX(0,1)
SETTINGS = {
    "A0": 0.0,         # Z
    "A1": math.pi / 2, # X
    "B0": math.pi / 4,
    "B1": -math.pi / 4,
    "B2": 0.0,         # key basis Z
    "B3": math.pi / 2, # key basis X
}

ALICE_ORDER = ["A0", "A1"]
BOB_ORDER = ["B0", "B1", "B2", "B3"]

CHSH_SETTING_LABELS = [
    ("A0", "B0"),
    ("A0", "B1"),
    ("A1", "B0"),
    ("A1", "B1"),
]

KEY_SETTING_LABELS = [
    ("A0", "B2"),
    ("A1", "B3"),
]



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run E91/BBM92 hardware proof with CHSH + QBER metrics."
    )
    parser.add_argument(
        "--backend",
        default="ibm_fez",
        help="IBM backend name",
    )
    parser.add_argument(
        "--instance",
        default="open-instance",
        help="IBM runtime instance name",
    )
    parser.add_argument(
        "--shots",
        type=int,
        default=2048,
        help="Shots per setting per repetition",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="Hardware repetitions for proof",
    )
    parser.add_argument(
        "--optimization-level",
        type=int,
        default=1,
        choices=(0, 1, 2, 3),
        help="IBM transpiler optimization level",
    )
    parser.add_argument(
        "--output",
        default="results/e91_proof_hardware.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260415,
        help="Seed used for deterministic shot post-processing order."
    )
    return parser.parse_args()


def aggregate(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    mean_v = mean(values)
    stdev_v = pstdev(values) if len(values) > 1 else 0.0
    ci95 = 0.0 if len(values) <= 1 else 1.96 * (stdev_v / math.sqrt(len(values)))
    return mean_v, stdev_v, ci95


def bell_pair_circuit(theta_a: float, theta_b: float) -> QuantumCircuit:
    circuit = QuantumCircuit(2, 2, name=f"e91_{theta_a:.3f}_{theta_b:.3f}")
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.ry(-theta_a, 0)
    circuit.ry(-theta_b, 1)
    circuit.measure([0, 1], [0, 1])
    return circuit


def build_circuit_library() -> dict[tuple[str, str], QuantumCircuit]:
    library = {}
    for a_label in ALICE_ORDER:
        for b_label in BOB_ORDER:
            a_theta = SETTINGS[a_label]
            b_theta = SETTINGS[b_label]
            library[(a_label, b_label)] = bell_pair_circuit(a_theta, b_theta)
    return library


def expectation_from_counts(counts: dict[str, int]) -> tuple[float, float]:
    # return: E (correlation), qber (in these raw bit pair data)
    total = sum(counts.values())
    if total <= 0:
        return 0.0, 0.0

    # bitstrings are two characters where each char is 0/1 for a measurement outcome.
    c00 = counts.get("00", 0)
    c11 = counts.get("11", 0)
    c01 = counts.get("01", 0)
    c10 = counts.get("10", 0)

    expectation = (c00 + c11 - c01 - c10) / total
    mismatch = (c01 + c10) / total
    return expectation, mismatch


def compute_metrics(run_counts: dict[tuple[str, str], dict[str, int]]) -> dict[str, float]:
    e00, _ = expectation_from_counts(run_counts[("A0", "B0")])
    e01, _ = expectation_from_counts(run_counts[("A0", "B1")])
    e10, _ = expectation_from_counts(run_counts[("A1", "B0")])
    e11, _ = expectation_from_counts(run_counts[("A1", "B1")])

    s_value = e00 + e01 + e10 - e11

    # matched-basis QBER from key basis rounds (A0/B2 and A1/B3)
    mismatch_counts = 0.0
    key_shots = 0
    for a_label, b_label in KEY_SETTING_LABELS:
        _, qber_component = expectation_from_counts(run_counts[(a_label, b_label)])
        pair_shots = sum(run_counts[(a_label, b_label)].values())
        mismatch_counts += qber_component * pair_shots
        key_shots += pair_shots

    qber = mismatch_counts / key_shots if key_shots > 0 else 0.0

    return {
        "E_A0_B0": e00,
        "E_A0_B1": e01,
        "E_A1_B0": e10,
        "E_A1_B1": e11,
        "S": s_value,
        "QBER": qber,
    }


def ideal_metrics() -> dict[str, float]:
    e00 = math.cos(SETTINGS["A0"] - SETTINGS["B0"])
    e01 = math.cos(SETTINGS["A0"] - SETTINGS["B1"])
    e10 = math.cos(SETTINGS["A1"] - SETTINGS["B0"])
    e11 = math.cos(SETTINGS["A1"] - SETTINGS["B1"])
    s_value = e00 + e01 + e10 - e11

    key_mismatch = 0.0

    return {
        "E_A0_B0": e00,
        "E_A0_B1": e01,
        "E_A1_B0": e10,
        "E_A1_B1": e11,
        "S": s_value,
        "QBER": key_mismatch,
    }


def run_hardware_repetition(
    sampler: SamplerV2,
    circuits: list[QuantumCircuit],
    labels: list[tuple[str, str]],
    shots: int,
) -> dict[str, Any]:
    job = sampler.run(circuits, shots=shots)
    result = job.result()

    run_counts: dict[tuple[str, str], dict[str, int]] = {}
    per_setting = []

    for pub, label in zip(result, labels):
        data = pub.data.c.get_counts()
        run_counts[label] = data
        per_setting.append({
            "setting": f"{label[0]}_{label[1]}",
            "shots": sum(data.values()),
            "counts": data,
        })

    metrics = compute_metrics(run_counts)
    strict_success = (metrics["S"] >= CHSH_THRESHOLD) and (metrics["QBER"] <= QBER_THRESHOLD)

    return {
        "job_id": job.job_id(),
        "settings": per_setting,
        "metrics": metrics,
        "strict_success": strict_success,
    }


def main() -> None:
    args = parse_args()
    rng = np.random.default_rng(args.seed)

    service = QiskitRuntimeService(instance=args.instance)
    backend = service.backend(args.backend)

    pass_manager: PassManager = generate_preset_pass_manager(
        backend=backend,
        optimization_level=args.optimization_level,
    )

    circuits_by_label = build_circuit_library()
    # Deterministic circuit order for reproducible summary across runs
    labels = sorted(circuits_by_label.keys())
    circuits = [pass_manager.run(circuits_by_label[label]) for label in labels]

    print(f"Backend: {backend.name}")
    print(f"Settings: {labels}")

    ideal = ideal_metrics()
    print(
        "Ideal (sim) S={S:.6f} QBER={QBER:.6f}".format(
            S=ideal["S"],
            QBER=ideal["QBER"],
        )
    )

    sampler = SamplerV2(mode=backend)

    repetitions = max(1, int(args.repetitions))
    runs = []
    s_values: list[float] = []
    qber_values: list[float] = []

    for run_index in range(1, repetitions + 1):
        run_seed = int(rng.integers(0, 2**31 - 1))
        run_result = run_hardware_repetition(
            sampler=sampler,
            circuits=circuits,
            labels=labels,
            shots=args.shots,
        )

        run_payload = {
            "run_index": run_index,
            "seed": run_seed,
            "job_id": run_result["job_id"],
            "metrics": run_result["metrics"],
            "strict_success": run_result["strict_success"],
            "settings": run_result["settings"],
        }
        runs.append(run_payload)
        s_values.append(run_result["metrics"]["S"])
        qber_values.append(run_result["metrics"]["QBER"])

        print(
            f"Run {run_index}: S={run_result['metrics']['S']:.6f}, "
            f"QBER={run_result['metrics']['QBER']:.6f}, "
            f"job={run_result['job_id']}, pass={run_result['strict_success']}"
        )

    mean_s, std_s, ci95_s = aggregate(s_values)
    mean_qber, std_qber, ci95_qber = aggregate(qber_values)
    strict_success_rate = sum(1 for run in runs if run["strict_success"]) / repetitions

    payload = {
        "experiment": "e91_qkd_hardware_proof",
        "protocol": "E91_BBM92_like",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "backend": backend.name,
        "instance": args.instance,
        "mode": "proof_hardware",
        "seed": args.seed,
        "shots": args.shots,
        "repetitions": repetitions,
        "optimization_level": args.optimization_level,
        "settings": {
            "alice": {
                "A0": SETTINGS["A0"],
                "A1": SETTINGS["A1"],
            },
            "bob": {
                "B0": SETTINGS["B0"],
                "B1": SETTINGS["B1"],
                "B2": SETTINGS["B2"],
                "B3": SETTINGS["B3"],
            },
        },
        "thresholds": {
            "chsh": CHSH_THRESHOLD,
            "qber": QBER_THRESHOLD,
            "strict_criterion": "S >= 2.15 and QBER <= 0.12",
        },
        "ideal_metrics": ideal,
        "aggregate": {
            "mean_S": mean_s,
            "std_S": std_s,
            "ci95_S": ci95_s,
            "mean_QBER": mean_qber,
            "std_QBER": std_qber,
            "ci95_QBER": ci95_qber,
            "strict_success_rate": strict_success_rate,
            "success_count": int(sum(1 for run in runs if run["strict_success"])),
        },
        "runs": runs,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Saved proof: {output_path}")
    print(
        f"Aggregate: mean S={mean_s:.6f} ± {ci95_s:.6f} (95%), "
        f"QBER={mean_qber:.6f} ± {ci95_qber:.6f} (95%), "
        f"success={payload['aggregate']['success_count']}/{repetitions}"
    )


if __name__ == "__main__":
    main()
