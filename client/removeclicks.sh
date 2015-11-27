#!/bin/bash
DEVICEID="0071ae7610994b1d"

#for CLICKS in `adb -s $DEVICEID shell click list | grep "."  | tr "	" " " `
adb -s $DEVICEID shell click list |  tr "	" " " | while read line
do
  REMOVECLICK="sudo click unregister $line"
  echo "$REMOVECLICK"
done
