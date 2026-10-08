// Jetracer dashboard entry point for rmf-dashboard-framework.
//
// Derived from rmf-web's examples/demo/main.tsx (Apache-2.0, Open Source
// Robotics Foundation), changed in exactly two places -- see DIFF markers.
// Everything else is upstream's demo verbatim, so diffing against it stays easy.
//
// This file lives in jetracer_fleet and is copied into the rmf-web checkout at
// build time by build_jetracer_dashboard.sh, so rmf-web itself stays unforked.

import '@fontsource/roboto/300.css';
import '@fontsource/roboto/400.css';
import '@fontsource/roboto/500.css';
import '@fontsource/roboto/700.css';

import ReactDOM from 'react-dom/client';
import {
  InitialWindow,
  LocallyPersistentWorkspace,
  MicroAppManifest,
  RmfDashboard,
  Workspace,
} from 'rmf-dashboard-framework/components';
import {
  createMapApp,
  doorsApp,
  liftsApp,
  robotMutexGroupsApp,
  robotsApp,
  tasksApp,
} from 'rmf-dashboard-framework/micro-apps';
import { StubAuthenticator } from 'rmf-dashboard-framework/services';

// ---------------------------------------------------------------------------
// DIFF 1 of 2: zoom, sized for a 13m lab instead of a building.
//
// The map uses an ORTHOGRAPHIC three.js camera, and react-three-fiber builds its
// frustum from canvas pixels, so:
//
//     visible world width (metres) = canvasWidth (px) / zoom
//
// Upstream's demo uses defaultZoom: 6. On a 1900px canvas that is ~317 m of
// visible world. The jetracer floorplan is 269 x 273 px at scale 0.05 =
// 13.45 x 13.65 m, so at zoom 6 it renders about 4% of the viewport wide -- a
// few dozen pixels of a mostly-white PNG, indistinguishable from a blank map.
//
// 85 puts the map at roughly 60-70% of the viewport width on a 1600-1900px
// canvas. To retune: zoom = canvasWidth / (mapWidthMetres / desiredFraction).
//
// defaultRobotZoom is what a click-to-zoom-on-robot jumps to. Upstream's ratio
// is 20/6 ~= 3.3x; 200 keeps a similar feel here (~9.5 m visible at 1900px).
const mapApp = createMapApp({
  attributionPrefix: 'Open-RMF',
  defaultMapLevel: 'L1',
  defaultRobotZoom: 200,
  defaultZoom: 85,
});
// ---------------------------------------------------------------------------

const appRegistry: MicroAppManifest[] = [
  mapApp,
  doorsApp,
  liftsApp,
  robotsApp,
  robotMutexGroupsApp,
  tasksApp,
];

const homeWorkspace: InitialWindow[] = [
  {
    layout: { x: 0, y: 0, w: 12, h: 6 },
    microApp: mapApp,
  },
];

const robotsWorkspace: InitialWindow[] = [
  {
    layout: { x: 0, y: 0, w: 7, h: 4 },
    microApp: robotsApp,
  },
  { layout: { x: 8, y: 0, w: 5, h: 8 }, microApp: mapApp },
  { layout: { x: 0, y: 0, w: 7, h: 4 }, microApp: doorsApp },
  { layout: { x: 0, y: 0, w: 7, h: 4 }, microApp: liftsApp },
  { layout: { x: 8, y: 0, w: 5, h: 4 }, microApp: robotMutexGroupsApp },
];

const tasksWorkspace: InitialWindow[] = [
  { layout: { x: 0, y: 0, w: 7, h: 8 }, microApp: tasksApp },
  { layout: { x: 8, y: 0, w: 5, h: 8 }, microApp: mapApp },
];

// Docker serves all browser connections through nginx on the current origin.
// Keep the native Vite development workflow's endpoints as defaults.
const sameOrigin = import.meta.env.VITE_RMF_SAME_ORIGIN === 'true';
const apiServerUrl = sameOrigin ? `${window.location.origin}/api` : 'http://localhost:8000';
const trajectoryServerUrl = sameOrigin
  ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/trajectory`
  : 'ws://localhost:8006';

export default function App() {
  return (
    <RmfDashboard
      apiServerUrl={apiServerUrl}
      trajectoryServerUrl={trajectoryServerUrl}
      authenticator={new StubAuthenticator()}
      helpLink="https://osrf.github.io/ros2multirobotbook/rmf-core.html"
      reportIssueLink="https://github.com/open-rmf/rmf-web/issues"
      resources={{ fleets: {}, logos: { header: '/resources/defaultLogo.png' } }}
      tasks={{
        // -------------------------------------------------------------------
        // DIFF 2 of 2: patrol only.
        //
        // Upstream also offers delivery, compose-clean and custom_compose. This
        // fleet cannot perform any of them: delivery needs dispensers/ingestors
        // at pickup/dropoff and the jetracer map has none, and both compose
        // tasks need action plugins that are not configured. Leaving them in
        // means three buttons that accept a submission and then fail.
        //
        // 'patrol' maps to the `loop` capability in jetracer_fleet_config.yaml.
        // A single-waypoint patrol is effectively go_to_place.
        allowedTasks: [{ taskDefinitionId: 'patrol' }],
        // -------------------------------------------------------------------
        pickupZones: [],
        cartIds: [],
      }}
      tabs={[
        {
          name: 'Map',
          route: '',
          element: <Workspace initialWindows={homeWorkspace} />,
        },
        {
          name: 'Robots',
          route: 'robots',
          element: <Workspace initialWindows={robotsWorkspace} />,
        },
        {
          name: 'Tasks',
          route: 'tasks',
          element: <Workspace initialWindows={tasksWorkspace} />,
        },
        {
          name: 'Custom',
          route: 'custom',
          element: (
            <LocallyPersistentWorkspace
              defaultWindows={[]}
              allowDesignMode
              appRegistry={appRegistry}
              storageKey="custom-workspace"
            />
          ),
        },
      ]}
    />
  );
}

const root = ReactDOM.createRoot(document.getElementById('root') as HTMLElement);
root.render(<App />);
