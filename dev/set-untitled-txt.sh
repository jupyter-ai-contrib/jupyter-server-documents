#!/bin/bash
# Sets the content `untitled.txt`, triggering an out-of-band change. This
# happens after 5 seconds.

echo "Triggering out-of-band change in 5 seconds..."

sleep 5
date +%T > untitled.txt

echo "Reset content of 'untitled.txt' to a timestamp."
