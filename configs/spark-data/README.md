# spark-data

The box's `/data` (17 TB HDD) mounted on the Spark at `/data` by NFS over the direct link, so files on the HDD can be
read and written from the Spark without copying. Box: `apt-get install -y nfs-kernel-server`, `box-exports` into
`/etc/exports.d/spark-data.exports`, `exportfs -ra`. Spark: the `spark-fstab` line into `/etc/fstab`, `mkdir -p /data`,
`systemctl daemon-reload && systemctl restart remote-fs.target`. The HDD is slow next to either NVMe: a model the Spark
serves is copied to its own `/models`, not read through this mount.
