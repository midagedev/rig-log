#!/bin/bash
# The workstation–Spark ConnectX link, checked from the Mac (log 2026-11-24 cx-link): a witness of both ends, a DF
# jumbo ping, iperf3 TCP, RDMA perftest (RoCE v2 through rdma_cm) in both directions, and the TCP round trip of
# wire-pingpong.py at MTU 9000 and, temporarily, 1500. The workstation is always the client of the TCP tests; the
# RDMA tests swap the server so each direction is the client's write/read.
# Not a lease measurement: a link check, run out of the timing lease, so its numbers carry no lease witness.
#
# usage: tools/spark/cx-link-test.sh OUTDIR
# env:   WS=ws SPARK=spark (ssh names)  WS_IF=enp2s0f1np1 SPARK_IF=enp1s0f0np0  WS_DEV=mlx5_1 SPARK_DEV=rocep1s0f0  MTU=9000
# needs: perftest + iperf3 on both ends, python3 on both. Server processes are started with their pid written to a
#        file on the remote end and stopped by that pid only.
set -u
OUT=${1:?usage: cx-link-test.sh OUTDIR}
WS=${WS:-ws} SPARK=${SPARK:-spark}
WS_IF=${WS_IF:-enp2s0f1np1} SPARK_IF=${SPARK_IF:-enp1s0f0np0}
WS_DEV=${WS_DEV:-mlx5_1} SPARK_DEV=${SPARK_DEV:-rocep1s0f0}
MTU=${MTU:-9000}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
v4(){ ssh "$1" "ip -4 -o addr show dev $2" | awk '{split($4,a,"/"); print a[1]; exit}'; }  # host iface
WS_IP=$(v4 "$WS" "$WS_IF") SPARK_IP=$(v4 "$SPARK" "$SPARK_IF")
[ -n "$WS_IP" ] && [ -n "$SPARK_IP" ] || { echo "no IPv4 on $WS:$WS_IF or $SPARK:$SPARK_IF" >&2; exit 2; }
log(){ echo "## $*" | tee -a "$OUT/summary.txt"; }

witness(){ # host iface
  ssh "$1" "hostname; uname -r; cat /proc/loadavg; sudo -n ethtool $2 | grep -E 'Speed|Link detected'; \
    sudo -n ethtool --show-fec $2 | grep -i active; ip -br link show $2; sudo -n ethtool -i $2 | grep -E 'driver|firmware'; \
    sudo -n lspci -vv -s \$(basename \$(readlink -f /sys/class/net/$2/device)) | grep LnkSta:; \
    sysctl net.core.busy_read net.core.busy_poll"
}
set_mtu(){ ssh "$WS" "sudo -n ip link set $WS_IF mtu $1" && ssh "$SPARK" "sudo -n ip link set $SPARK_IF mtu $1"; }
remote_bg(){ # host pidfile cmd...  start a server, record its pid on the remote end
  local h=$1 pf=$2; shift 2
  ssh "$h" "nohup $* >$pf.log 2>&1 </dev/null & echo \$! > $pf"
  sleep 2
}
remote_stop(){ ssh "$1" "[ -f $2 ] && kill \$(cat $2) 2>/dev/null; rm -f $2; true"; }

log "witness $(date -u +%FT%TZ)"
{ witness "$WS" "$WS_IF"; echo; witness "$SPARK" "$SPARK_IF"; } > "$OUT/witness.txt" 2>&1
cat "$OUT/witness.txt" >> "$OUT/summary.txt"

log "DF ping 8972 B, $WS -> $SPARK_IP"
ssh "$WS" "ping -M do -s 8972 -c 5 -i 0.2 $SPARK_IP" > "$OUT/ping.txt" 2>&1
tail -2 "$OUT/ping.txt" | tee -a "$OUT/summary.txt"

log "iperf3 TCP 10 s (Gb/s receiver side)"
for p in 1 4 8; do
  for dir in fwd rev; do
    remote_bg "$SPARK" /tmp/cx-iperf3.pid iperf3 -s -1 -B "$SPARK_IP"
    r=""; [ "$dir" = rev ] && r="-R"
    ssh "$WS" "iperf3 -c $SPARK_IP -B $WS_IP -t 10 -P $p $r" > "$OUT/iperf3-P$p-$dir.txt" 2>&1
    remote_stop "$SPARK" /tmp/cx-iperf3.pid
    line=$(grep -E 'receiver' "$OUT/iperf3-P$p-$dir.txt" | tail -1)
    retr=$(grep -E 'sender' "$OUT/iperf3-P$p-$dir.txt" | tail -1 | awk '{print $(NF-1)}')
    d="ws->spark"; [ "$dir" = rev ] && d="spark->ws"
    echo "P=$p $d: $(echo "$line" | grep -oE '[0-9.]+ Gbits/sec') retr=$retr" | tee -a "$OUT/summary.txt"
  done
done

log "RDMA perftest (RoCE v2, rdma_cm), BW in Gb/s, 5 s"
bw(){ # test qps srvhost srvdev clihost clidev srvip tag
  remote_bg "$3" /tmp/cx-perf.pid timeout 60 "$1" -d "$4" -R -F --report_gbits -D 5 -q "$2"
  ssh "$5" "timeout 60 $1 -d $6 -R -F --report_gbits -D 5 -q $2 $7" > "$OUT/$1-q$2-$8.txt" 2>&1
  remote_stop "$3" /tmp/cx-perf.pid
  echo "$1 q=$2 $8: $(awk '/^ *65536/{print "avg", $4, "Gb/s"}' "$OUT/$1-q$2-$8.txt")" | tee -a "$OUT/summary.txt"
}
for t in ib_write_bw ib_read_bw ib_send_bw; do
  for q in 1 4; do
    bw $t $q "$SPARK" "$SPARK_DEV" "$WS" "$WS_DEV" "$SPARK_IP" "ws-client"
    bw $t $q "$WS" "$WS_DEV" "$SPARK" "$SPARK_DEV" "$WS_IP" "spark-client"
  done
done

log "RDMA latency, µs (t_typical / t_avg / 99%), 10000 iters, ws client"
for t in ib_write_lat ib_send_lat; do
  for s in 64 8192 16384; do
    remote_bg "$SPARK" /tmp/cx-perf.pid timeout 60 "$t" -d "$SPARK_DEV" -R -F -s "$s" -n 10000
    ssh "$WS" "timeout 60 $t -d $WS_DEV -R -F -s $s -n 10000 $SPARK_IP" > "$OUT/$t-$s.txt" 2>&1
    remote_stop "$SPARK" /tmp/cx-perf.pid
    echo "$t $s B: $(awk -v s="$s" '$1==s{print "typ", $5, "avg", $6, "p99", $8}' "$OUT/$t-$s.txt")" | tee -a "$OUT/summary.txt"
  done
done

for m in "$MTU" 1500; do
  log "TCP round trip (wire-pingpong.py, µs), MTU $m"
  set_mtu "$m"
  scp -q "$HERE/wire-pingpong.py" "$SPARK:/tmp/wire-pingpong.py"
  scp -q "$HERE/wire-pingpong.py" "$WS:/tmp/wire-pingpong.py"
  remote_bg "$SPARK" /tmp/cx-pp.pid python3 /tmp/wire-pingpong.py serve --bind "$SPARK_IP"
  ssh "$WS" "python3 /tmp/wire-pingpong.py client $SPARK_IP --sizes 64,8192,16384,1048576" > "$OUT/pingpong-mtu$m.txt" 2>&1
  remote_stop "$SPARK" /tmp/cx-pp.pid
  tee -a "$OUT/summary.txt" < "$OUT/pingpong-mtu$m.txt"
done
set_mtu "$MTU"
log "MTU restored to $MTU; done $(date -u +%FT%TZ)"
