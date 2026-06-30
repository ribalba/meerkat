/* Entry point: start the app once the DOM is ready. Loaded last, after every
 * app.*.js module has registered itself on window.App. */
(function () {
  "use strict";
  window.jQuery(document).ready(() => window.App.boot());
})();
