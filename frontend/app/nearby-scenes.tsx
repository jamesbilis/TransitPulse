type StopPhoto = {
  image: string;
  source: string;
  artist: string;
  license_url: string;
  license_name: string;
};

async function getPhoto(route: string, station: string, night: boolean): Promise<StopPhoto | null> {
  const params = new URLSearchParams({ station, night: String(night) });
  try {
    const response = await fetch(
      `http://127.0.0.1:8000/api/routes/${encodeURIComponent(route)}/stop-photo?${params}`,
      { cache: "no-store", signal: AbortSignal.timeout(6_000) },
    );
    if (!response.ok) return null;
    const photo = await response.json() as StopPhoto | null;
    return photo && /^https:\/\/(?:thumb|upload)\.wikimedia\.org\/wikipedia\/commons\/thumb\/[a-z0-9/%._:-]+$/i.test(photo.image)
      ? photo
      : null;
  } catch {
    return null;
  }
}

function PhotoCredit({ photo, night }: { photo: StopPhoto | null; night: boolean }) {
  return (
    <p className={`scene-credit ${night ? "night-credit" : "day-credit"}`}>
      {photo ? (
        <>
          Nearby photo by <a href={photo.source}>{photo.artist}</a>
          {" · "}<a href={photo.license_url}>{photo.license_name}</a>
          {" · Resized and cropped"}
        </>
      ) : (
        <>No nearby {night ? "nighttime" : "daytime"} photo available.</>
      )}
    </p>
  );
}

export default async function NearbyScenes({ route, station }: { route: string; station: string }) {
  const [day, night] = await Promise.all([
    getPhoto(route, station, false),
    getPhoto(route, station, true),
  ]);
  const variables = [
    day && `--day-scene: url("${day.image}");`,
    night && `--night-scene: url("${night.image}");`,
  ].filter(Boolean).join(" ");

  return (
    <div className="nearby-scenes">
      {variables && <style>{`body:has(.nearby-scenes) { ${variables} }`}</style>}
      <PhotoCredit photo={day} night={false} />
      <PhotoCredit photo={night} night />
    </div>
  );
}
