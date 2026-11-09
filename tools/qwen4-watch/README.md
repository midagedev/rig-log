# qwen4-watch

The box looks for Qwen4 weights on Hugging Face every 2 h (`qwen4-watch.timer`) and starts their download into
`/models/<repo name>` the moment a `Qwen/Qwen4…` or `unsloth/Qwen4…` repo appears (`watch.py` says what it fetches). The
lead's session reads `/root/qwen4-watch/FOUND` and opens the model's rounds.

Install (root on the box):

    mkdir -p /root/qwen4-watch/hf-fetch
    cp watch.py /root/qwen4-watch/ && cp ../../configs/hf-fetch/hf-{manifest.py,worker.sh} /root/qwen4-watch/hf-fetch/
    cp qwen4-watch.service qwen4-watch.timer /etc/systemd/system/ && systemctl daemon-reload
    systemctl enable --now qwen4-watch.timer

Remove once the model is in: `systemctl disable --now qwen4-watch.timer`.
