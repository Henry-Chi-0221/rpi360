# Web workspace

Follow the root README to build WASM and start Vite. Open `http://localhost:5173`.
The camera is optional; included still-frame samples work immediately.

- Drag the viewer to change orientation; scroll or use **Field of view** to zoom.
- Choose an effect, scrub its timeline, then adjust the view and **Add keyframe**.
- **Save edit** stores a project in IndexedDB. Download the project JSON from the
  export dialog to keep a portable copy. Source media is never embedded in it.
- Import a legacy `.r360.mp4`, a `.r360` folder, or a stored `.r360.zip` bundle.
  New bundles are checksum-verified before use. Unknown legacy synchronization
  remains unknown; use the alignment control only after visually checking it.
- Camera downloads go to origin-private storage. Interrupted file transfers can
  resume. Remove local copies in the library to reclaim space; camera originals
  are not deleted.
- Export a reframed H.264 MP4 or a 2:1 equirectangular MP4 with spherical metadata.
  The browser must support the selected H.264 decoder and encoder profile.

The current browser adapter copies decoded pixels through a bounded canvas into
wgpu. It is not a zero-copy renderer. Large source frames and export performance
vary by device. No unsupported operation is silently sent to a cloud service.

Storage belongs to the exact browser origin. Clearing site data removes local
projects and downloaded copies. Keep independent backups of original recordings
and exported project JSON.
