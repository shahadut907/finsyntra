/**
 * Fixed ambient background: aurora blobs + financial grid texture.
 * Pure CSS animation on transform only; one shared instance for the
 * whole app (z-index -2), so it costs nothing per route.
 */
export default function Atmosphere() {
  return (
    <div className="atmosphere" aria-hidden="true">
      <div className="atmosphere__grid" />
      <div className="atmosphere__blob atmosphere__blob--a" />
      <div className="atmosphere__blob atmosphere__blob--b" />
      <div className="atmosphere__blob atmosphere__blob--c" />
    </div>
  );
}
