# YouTube ingestion

V4 provides video-ID and metadata/transcript normalization utilities. Metadata
can be retained without downloading video bytes, and caption segments normalize
to timestamped Markdown. Captions are only ingested when supplied by a
legitimate permitted mechanism; unavailable captions remain metadata-only.
