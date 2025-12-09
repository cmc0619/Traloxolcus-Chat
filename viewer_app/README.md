# Processing Station Viewer

Static single-page viewer for stitched sessions and event search. The page is served from its own container (nginx) and talks to the processing-station API over HTTP Basic auth.

## Build and run

```
docker build -t processing-station-viewer -f viewer_app/Dockerfile viewer_app
# serve on port 8080
docker run -p 8080:80 processing-station-viewer
```

Once running, open `http://localhost:8080` and set the API base URL (e.g. `http://localhost:8001`), username, and password. Settings are stored only in your browser’s local storage.
