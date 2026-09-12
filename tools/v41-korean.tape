# rig-log 002 — a 347 GB model answering in Korean, with 84 GB of it on a drive.
#
# The left pane is the model. The right pane is why it is worth recording: the
# same 347 GB file split across two GPUs, system RAM, and an NVMe that is never
# read into memory at all. The sparkline is engram — DeepSeek-V4.1's conditional
# memory, 384 million rows, read a few dozen at a time straight off the disk.
#
# The demo runs ON the workstation, because the numbers come from /proc next to
# the server. VHS drives a local shell that ssh's in, so the host stays out of
# this repo: set RIG_SSH to the ssh target before recording.
#
#   export RIG_SSH=user@your-host
#   vhs tools/v41-korean.tape
#
# Compress (GIF is for the repo; post the mp4 to Twitter, it is ~10x smaller):
#   gifsicle -O3 --colors 96 --lossy=60 -o assets/v41-korean.gif assets/v41-korean.gif
#   ffmpeg -i assets/v41-korean.gif -movflags faststart -pix_fmt yuv420p \
#          -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" assets/v41-korean.mp4
#
# D2Coding, because the panel is drawn with box characters and aligned by
# counting Korean as two columns. A font that renders Hangul at anything other
# than exactly twice the Latin advance tears the right border apart.

Output assets/v41-korean.gif

Set Shell "bash"
Set FontSize 15
Set FontFamily "D2Coding, Menlo, Monaco, monospace"
Set Width 1130
Set Height 580
Set Theme {"name":"blueprint","background":"#11161a","foreground":"#d6dee4","cursor":"#64c8d8","selection_background":"#24323c","black":"#11161a","red":"#d97a63","green":"#7cc4a0","yellow":"#e3c583","blue":"#64c8d8","magenta":"#a894c8","cyan":"#64c8d8","white":"#d6dee4","brightBlack":"#5c6a75","brightRed":"#e39580","brightGreen":"#93d4b3","brightYellow":"#f0d8a0","brightBlue":"#8ad9e6","brightMagenta":"#bfaeda","brightCyan":"#8ad9e6","brightWhite":"#f2f6f8"}
Set Padding 16
Set Framerate 10
Set TypingSpeed 28ms
Set WindowBar Colorful
Set BorderRadius 8
Set WaitTimeout 300s

Hide
Type "clear"
Enter
Show

Sleep 600ms

Type "ssh $RIG_SSH 'COLUMNS=132 ROWS=28 python3 v41-demo.py'"
Sleep 500ms
Enter

# 2000 tokens at about 17 tok/s once the context is long: roughly two minutes.
# The answer pane scrolls; the right panel keeps updating throughout.
Sleep 122s
