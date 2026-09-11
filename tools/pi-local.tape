# rig-log 001 — a 284 B mixture-of-experts model answering from one workstation.
#
# Act 1: pi, interactive, streaming the model's reasoning and then its code.
# Act 2: configs/tps.py — the same server, tokens printed as they arrive, and
#        the decode rate read out of the server's own timings block.
#
# The model is DeepSeek-V4-Flash-0731 as 155 GB of four-bit GGUF, served by
# ik_llama.cpp with routed experts split across an A6000, a 3090 and 256 GB
# of DDR4. The client is a laptop on the other end of a Tailscale link.
#
# Record:   vhs tools/pi-local.tape
# Compress: gifsicle -O3 --colors 96 --lossy=45 -o assets/pi-local.gif assets/pi-local.gif
#
# pi runs with tools, skills, extensions and session storage disabled: an
# approval prompt mid-take would stall the recording. The system prompt is
# replaced as well — the default one advertises tools, and the model then
# answers a code question by trying to list the directory.

Output assets/pi-local.gif

Set Shell "bash"
Set FontSize 17
Set FontFamily "D2Coding, Menlo, Monaco, monospace"
Set Width 1180
Set Height 620
Set Theme {"name":"blueprint","background":"#eef3f6","foreground":"#0d2b3e","cursor":"#a8331f","selection_background":"#cfdde6","black":"#0d2b3e","red":"#a8331f","green":"#1f6b4a","yellow":"#8a5a18","blue":"#0d5c7a","magenta":"#5a4a7a","cyan":"#2f8ca8","white":"#dfe7ec","brightBlack":"#7c9cb0","brightRed":"#c2432c","brightGreen":"#2f8560","brightYellow":"#a8701f","brightBlue":"#2f8ca8","brightMagenta":"#6f5c95","brightCyan":"#4aa8c2","brightWhite":"#f7fafb"}
Set Padding 14
Set Framerate 8
Set TypingSpeed 22ms
Set WindowBar Colorful
Set BorderRadius 6
Set WaitTimeout 180s

Hide
Type "cd $HOME/repo-mid/rig-log && clear"
Enter
Show

Sleep 400ms

Type "tools/pi-demo.sh"
Enter
Sleep 5s

Type "Implement a thread-safe LRU cache in Rust: the struct, the public API, eviction, and unit tests. Then explain the locking strategy."
Sleep 400ms
Enter

Sleep 30s

# Interrupt the stream, leave pi, and measure the same server directly.
Escape
Sleep 1200ms
Ctrl+D
Sleep 1200ms
Type "clear"
Enter
Sleep 300ms

Type "tools/tps-demo.sh"
Enter
Sleep 30s
