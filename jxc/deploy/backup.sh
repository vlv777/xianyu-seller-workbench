#!/bin/sh
# PocketBase 每日备份：打包 pb_data 到备份盘，保留 30 天
DATA=/opt/pocketbase/pb_data
DEST=/mnt/backup/pocketbase
mkdir -p "$DEST"
tar czf "$DEST/pb_data_$(date +%Y%m%d_%H%M).tar.gz" -C "$DATA" .
find "$DEST" -name "pb_data_*.tar.gz" -mtime +30 -delete
echo "backup done: $(date '+%F %T')"
