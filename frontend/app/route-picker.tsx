export type TransitRoute = {
  id: string;
  type: number;
  name: string;
  short_name: string;
  description: string;
  color: string;
  text_color: string;
};

export type TransitStop = { id: string; name: string };

function routeGroup(route: TransitRoute) {
  if (route.type === 0 || route.type === 1) return "Subway and trolley";
  if (route.type === 2) return "Commuter Rail";
  if (route.description === "Silver Line" || /^SL\d/i.test(route.short_name)) return "Silver Line";
  if (route.type === 3) return "Bus";
  if (route.type === 4) return "Ferry";
  return "Other services";
}

export function routeName(route: TransitRoute) {
  if (route.type === 3 && route.short_name && route.name) {
    return `${route.short_name} · ${route.name}`;
  }
  return route.name || route.short_name || route.id;
}

export default function RoutePicker({
  routes,
  currentRoute,
  unavailable,
}: {
  routes: TransitRoute[];
  currentRoute: TransitRoute;
  unavailable: boolean;
}) {
  const groups = new Map<string, TransitRoute[]>();
  for (const route of routes) {
    const group = routeGroup(route);
    const members = groups.get(group) ?? [];
    members.push(route);
    groups.set(group, members);
  }

  return (
    <form className="route-controls" method="get">
      <label htmlFor="mbta-route">MBTA route</label>
      <div className="route-control-row">
        <select id="mbta-route" name="route" defaultValue={currentRoute.id}>
          {[...groups].map(([name, members]) => (
            <optgroup key={name} label={name}>
              {members.map((route) => (
                <option key={route.id} value={route.id}>{routeName(route)}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <button type="submit" className="refresh">Change route</button>
      </div>
      {unavailable && <p className="message" role="status">The full route list is temporarily unavailable.</p>}
    </form>
  );
}
