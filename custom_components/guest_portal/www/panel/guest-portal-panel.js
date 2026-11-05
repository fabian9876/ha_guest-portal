class HaGuestPortalPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._path = null;
  }

  set panel(panel) {
    this._panel = panel;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  _render() {
    const path = this._panel && this._panel.config && this._panel.config.path;
    if (!path || path === this._path) return;
    this._path = path;

    const style = document.createElement("style");
    style.textContent = ":host{display:block;width:100%;height:100%}iframe{display:block;width:100%;height:100%;min-height:100vh;border:0;background:var(--primary-background-color,#fff)}";

    const frame = document.createElement("iframe");
    frame.src = path;
    frame.title = path.endsWith("/admin") ? "Gastverwaltung" : "Gästeportal";
    frame.referrerPolicy = "same-origin";
    this.shadowRoot.replaceChildren(style, frame);
  }
}

if (!customElements.get("ha-guest-portal-panel")) {
  customElements.define("ha-guest-portal-panel", HaGuestPortalPanel);
}
