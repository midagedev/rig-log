# spark-data

The box's `/data` (17 TB HDD) mounted on the Spark at `/data` by NFS over the direct link, so files on the HDD can be
read and written from the Spark without copying. Box: `apt-get install -y nfs-kernel-server`, `box-exports` into
`/etc/exports.d/spark-data.exports`, `exportfs -ra`. Spark: the `spark-fstab` line into `/etc/fstab`, `mkdir -p /data`,
`systemctl daemon-reload && systemctl restart remote-fs.target`. The HDD is slow next to either NVMe: a model the Spark
serves is copied to its own `/models`, not read through this mount.

## Taildrive and the tailnet link (the box's /data for every tailnet device)

- Taildrive: `tailscale drive share data /data` on the box (the tailnet policy gives every member `drive:share` and
  `drive:access` and an rw grant on every share). In Finder: Go → Connect to Server, `http://100.100.100.100:8080`, Guest;
  the share is at `<tailnet>/ws/data`. It serves as root, so a file written there is root's.
- Read-only link: `tailscale serve --bg --set-path /data /data` on the box (beside netdata on `/` and :8443), so
  `https://ws.<tailnet>/data/` lists and downloads in a browser. Off: `tailscale serve --set-path /data off`.
