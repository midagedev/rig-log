#!/usr/bin/env python3
"""ws+Spark cost model: decode and prefill of V4.1-Flash Q3_K_M on the box (A6000 stage) with the DGX Spark as a
TCP tier node, from measured constants, so a configuration is priced before a sitting (AGENTS.md "derive first").

Every constant names its source; [derived] marks a number that is a derivation, not a measurement. Run it with no
arguments for the table; `--check` prints the two 2026-11-05 sittings beside the model.
"""
import sys

# ---- measured constants (box = A6000 stage + EPYC host; Spark = GB10 over the direct 10GbE) ----
CARD_FRONT_MS = 17.0        # plan a decode step, kernels on the A6000 (nsys 2026-09-24)
STEP_A_MS = 19.4            # plan a warm step, residency mid, prose 512 n 96 (sittings 2026-11-05 06:55, 07:40, last10 p50)
STEP_A_P50_MS = 21.7        # plan a step p50 over the 96 tokens (the headline 46.0 tok/s(p50)); the gap model uses the warm step
HOST_WAIT_A_MS = STEP_A_MS - CARD_FRONT_MS   # exposed host wait at plan a [derived]
HOST_SLOT_MS = 0.14         # host leg per host slot (sparktier: 135-145 us a slot at 119 GB/s)
LAYERS = 40
A_RTT_FLOOR_US = 52         # 8 KiB TCP round trip on the direct link (sparktier 4.2)
A_ENGINE_US = (175, 240)    # node round trip a per layer as the lock sitting read it [derived, two readings]
LINK_GBPS = 1.24            # one-way TCP throughput on the 10GbE link (docs/contrib/dgx-spark, spark-wire-tuning)
GB10_GBPS = 209             # GB10 measured read bandwidth (sparktier: 208.8 GB/s)
NVME_GBPS_QD4 = 5.7         # box drive at QD 4 (qdsweep); 2.5 at QD 1
NODE_TIER_GB = 94.65        # the Spark tier at BLOOMERY_CARD_BUDGET=90G (5,643 of 7,499 experts)
NODE_SHARE = 5643 / 12692   # the node's share of the experts the host served at plan a [derived from the census]
# prefill, plan a, P 512 (card A sitting): card_in 36.1 ms a layer, host union 28.8 ms a layer; pp 220 = 2.33 s
PF_CARD_MS = 36.1
PF_HOST_MS = 28.8
PP_A = 220.0
P = 512
HIDDEN = 7168
N_USED = 6


def decode_split(a_us):
    """Experts split per layer (today): the node answers every layer, a round trip a each."""
    return STEP_A_MS + LAYERS * a_us / 1000.0


def decode_layer_pipeline(spark_layers, per_layer_ms):
    """The Spark holds whole layers: one round trip a step, the box runs the rest. per_layer_ms is the GB10's time
    for one layer of one token [derived: ~150 MB routed+dense bytes at 209 GB/s = 0.72 ms + launches ~0.2 ms]."""
    box = STEP_A_MS * (LAYERS - spark_layers) / LAYERS
    return box + spark_layers * per_layer_ms + 2 * A_RTT_FLOOR_US / 1000.0 + 0.2


def decode_streams(k, a_us, with_node):
    """k streams decoded together (bloomery-serve --parallel k): one step serves k rows. The host leg grows with the
    union of the k rows' routed experts [derived: union factor 1 + 0.75 (k-1) up to the pool]; the card front grows
    little (attention k rows, the card's experts' union). With the node, the node takes its share of the host union
    in ONE trip for all k rows (page MAX_ROWS = 4), so a is paid once a layer, not once a row. Host slots at plan a,
    one row: 83 a token (sparktier); host leg = slots x HOST_SLOT_MS, exposed only above the card front."""
    union = 1.0 + 0.75 * (k - 1)
    card = CARD_FRONT_MS * (1.0 + 0.06 * (k - 1))
    host_slots = 83 * union * ((1 - NODE_SHARE) if with_node else 1.0)
    host = host_slots * HOST_SLOT_MS
    node = (LAYERS * a_us / 1000.0) if with_node else 0.0
    step = max(card, host) + node
    return step, k * 1000.0 / step


def decode_bigger_quant(bpw, ram_gb=328.0, hot_hit=0.5):
    """A quant that does not fit the box (RAM 256 + A6000 48 + 3090 24 = 328 GB): ws alone pages the missing experts
    from NVMe each token; ws+Spark holds them on the node. Q3_K_M = 324 GB at ~3.44 bpw; bytes a token = 6 routed x 40
    layers x 19.3 MB x bpw/3.44 [derived]. hot_hit: the share of the missing bytes residency keeps in RAM [guess]."""
    file_gb = 324.0 * bpw / 3.44
    missing = max(0.0, file_gb - ram_gb + 20.0)   # 20 GB of KV, scratch and the page cache's floor [derived]
    tok_gb = 6 * LAYERS * 0.0193 * bpw / 3.44
    nvme_ms = tok_gb * (missing / file_gb) * (1 - hot_hit) / NVME_GBPS_QD4 * 1000.0
    ws_alone = STEP_A_MS * bpw / 3.44 + nvme_ms
    ws_spark = decode_split(200) * bpw / 3.44
    return file_gb, missing, ws_alone, ws_spark


def prefill_host_reads_node(cache_warm):
    """nodebatch today: the host serves the node's experts in the batch, read from the file each prompt."""
    per_layer_file_ms = NODE_TIER_GB / LAYERS / NVME_GBPS_QD4 * 1000.0 * (1.0 - cache_warm)
    per_layer = max(PF_CARD_MS, PF_HOST_MS * (1 - NODE_SHARE) + per_layer_file_ms)
    return P / (LAYERS * per_layer / 1000.0)


def prefill_node_computes(return_bytes_per_elem):
    """The node runs the block for its experts: send Q8 act, compute on the GB10, return its rows (Packed)."""
    send_mb = P * (HIDDEN + HIDDEN // 32 * 4) / 1e6
    ret_mb = NODE_SHARE * P * N_USED * HIDDEN * return_bytes_per_elem / 1e6
    link_ms = (send_mb + ret_mb) / LINK_GBPS / 1e3 * 1e3
    node_read_ms = NODE_TIER_GB / LAYERS / GB10_GBPS * 1000.0
    node_flops_ms = 5.0  # [derived] 2.7e11 flop a layer at ~50 TFLOPS realised
    node_leg = link_ms + node_read_ms + node_flops_ms
    per_layer = max(PF_CARD_MS, PF_HOST_MS * (1 - NODE_SHARE), node_leg)
    return P / (LAYERS * per_layer / 1000.0), node_leg


def main():
    print("decode, tok/s (1000/warm step ms); ws alone plan a warm %.1f (p50 over the run %.1f)" % (1000 / STEP_A_MS, 1000 / STEP_A_P50_MS))
    for a in (A_RTT_FLOOR_US, 110, *A_ENGINE_US):
        s = decode_split(a)
        print("  experts split per layer, a = %3d us: step %.1f ms -> %.1f tok/s" % (a, s, 1000 / s))
    for pl in (0.5, 0.75, 1.0):
        s = decode_layer_pipeline(10, pl)
        print("  Spark holds 10 whole layers at %.2f ms/layer: step %.1f ms -> %.1f tok/s [derived]" % (pl, s, 1000 / s))
    print("decode, k streams together (aggregate tok/s) [derived]")
    for k in (1, 2, 4):
        s0, t0 = decode_streams(k, 0, False)
        s1, t1 = decode_streams(k, 200, True)
        s2, t2 = decode_streams(k, 52, True)
        print("  k=%d: ws alone step %.1f ms %.0f tok/s | +Spark a 200 us: %.1f ms %.0f tok/s | a 52 us: %.1f ms %.0f tok/s" % (k, s0, t0, s1, t1, s2, t2))
    print("decode at a bigger quant than the box holds [derived]")
    for bpw, name in ((4.85, "Q4_K_M"), (5.7, "Q5_K_M")):
        f, m, wa, ws = decode_bigger_quant(bpw)
        print("  %s ~%.0f GB (%.0f GB past the box): ws alone %.1f ms -> %.1f tok/s (NVMe pages) | ws+Spark %.1f ms -> %.1f tok/s" % (name, f, m, wa, 1000 / wa, ws, 1000 / ws))
    print("prefill, pp tok/s at P 512; ws alone plan a = %.0f" % PP_A)
    for warm in (0.0, 0.5, 0.8):
        print("  host reads the node's experts from the file, cache %.0f %% warm: %.0f" % (warm * 100, prefill_host_reads_node(warm)))
    for nb, name in ((4, "f32"), (2, "bf16")):
        pp, leg = prefill_node_computes(nb)
        print("  node computes its block, %s rows back: node leg %.0f ms a layer -> %.0f (%+.0f %%) [derived]" % (name, leg, pp, (pp / PP_A - 1) * 100))
    if "--check" in sys.argv:
        print("check: sitting 07:40 node arm warm step 26.4-27.0 ms; model at a 175-240 us: %.1f-%.1f ms" % (decode_split(175), decode_split(240)))
        print("check: sitting 06:55/07:40 node arm pp 28-69; model cache 0-80 %% warm: %.0f-%.0f" % (prefill_host_reads_node(0), prefill_host_reads_node(0.8)))


if __name__ == "__main__":
    main()
