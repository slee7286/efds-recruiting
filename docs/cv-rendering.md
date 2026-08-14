# CV rendering

`recruiting artifact render-cv <application-id>` selects an approved CV version and evidence-backed bullets, generates LaTeX, compiles with the configured TeX engine, extracts PDF text with pypdf, and records hashes, page count, compiler output, and provenance. The default target is one page; overflow fails validation rather than silently deleting content.

