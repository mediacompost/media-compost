import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./shared/tokens.css";
import { App } from "./app/App";
import { ErrorBoundary } from "./shared/ErrorBoundary";
import { UpdateBanner } from "./app/components/UpdateBanner";

import { initTheme } from "./app/theme";
import { ApiError } from "./app/api";
import { setInvalidationClient } from "./app/invalidation";
import { installDragBodyClass } from "./shared/dragBody";
// For the side effect: registers the app's translation catalogs. `App.tsx`
// reaches the same facade anyway today, but `query/QueryBuilder.tsx` and
// `shared/HfWarnings.tsx` call `useT` straight from `shared/`, so an entry
// path that skipped the facade would silently translate nothing.
import "./app/i18n";

// Resolve and apply the light/dark/system theme before the first paint.
initTheme();
// Mark the document while any drag is in flight (see shared/dragBody.ts).
installDragBodyClass();

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      refetchOnWindowFocus: false,
      // A 4xx is the server saying the REQUEST is wrong, so asking again
      // identically cannot help. The default three retries with a growing
      // pause turned a refused search into about seven seconds of nothing
      // before the message was allowed on screen. A 5xx or a dropped
      // connection still gets the retries — those can genuinely pass.
      retry: (count, err) =>
        !(err instanceof ApiError && err.status >= 400 && err.status < 500)
        && count < 3,
    },
  },
});
// Wire the central (coalesced) invalidation helpers — which the page-level
// import engine also invalidates through as tasks progress — to this client.
setInvalidationClient(qc);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      {/* Mounted once, above the whole tree, so it floats over the library
          and the item-window overlay alike — every write in the app is
          refused on the same stale-build rule. */}
      <UpdateBanner />
      {/* ONE app. The item window is an OVERLAY inside it now (mounted by
          `App`, with a boundary of its own), not a second document — so this
          file has nothing left to route. `location.ts` reads which item, if
          any, the address has open, including every address the window wore
          while it was a window. */}
      <ErrorBoundary what="Media Compost" t={(s) => s}><App /></ErrorBoundary>
    </QueryClientProvider>
  </React.StrictMode>
);
