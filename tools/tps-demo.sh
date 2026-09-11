#!/usr/bin/env bash
# The measurement act of the recording: a request small enough that the model
# finishes inside the take, so the decode rate actually appears on screen.
# tps.py's own default asks for a full implementation and spends every token
# on reasoning.
exec python3 configs/tps.py "" \
  "Write a Rust struct for a fixed-size ring buffer with push and pop. Code plus two tests." \
  700
