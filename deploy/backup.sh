#!/bin/sh
# Nightly backup of the data volume (database, de-identified datasets, keys). Keep 30 days; copy to a second in-Kingdom location.
set -e
DEST=/var/backups/marsad-insights
mkdir -p "$DEST"
docker run --rm -v marsad-insights_insights-data:/data -v "$DEST":/backup alpine \
  tar czf "/backup/insights-$(date +%Y%m%d).tgz" -C /data .
find "$DEST" -name 'insights-*.tgz' -mtime +30 -delete
