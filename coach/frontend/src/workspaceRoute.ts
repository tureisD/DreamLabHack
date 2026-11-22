export const screens = ['runs', 'tasks', 'demos', 'guide', 'evaluation', 'training', 'preflight'] as const;
export type Screen = typeof screens[number];
export function readRoute(hash = window.location.hash) {
  const [path, query = ''] = hash.replace(/^#\/?/, '').split('?');
  const screen = screens.includes(path as Screen) ? path as Screen : 'runs';
  return { screen, query: new URLSearchParams(query) };
}
export function screenHref(screen: Screen, args: Record<string, string> = {}) {
  const selected = readRoute().query.get('task');
  const query = new URLSearchParams({...selected ? {task: selected} : {}, ...args}).toString();
  return `#/${screen}${query ? `?${query}` : ''}`;
}
export function selectTask(task: string) {
  const current = readRoute();
  if (task && current.query.get('task') !== task) window.location.hash = screenHref(current.screen, {task});
}
export function initialTask<T extends { id: string }>(tasks: T[]) {
  return tasks.find(task => task.id === readRoute().query.get('task')) ?? tasks[0];
}
