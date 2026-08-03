var Zotero;

var { install, onMainWindowLoad, onMainWindowUnload, shutdown, startup, uninstall } = (() => {
  var __name = (target, value) => Object.defineProperty(target, "name", { value, configurable: true });

  const { interfaces: Ci, results: Cr, utils: Cu } = Components;
  const PREFS = "extensions.zotero.reaper.";

  function log(msg) { Zotero.debug("Reaper: " + msg); }
  function pref(key, fallback) { try { var v = Zotero.Prefs.get(PREFS + key); return (v != null) ? v : fallback; } catch (e) { return fallback; } }
  function serverURL() { return "http://localhost:" + pref("serverPort", "16625"); }
  function buildTitle(arxivID, source, light) {
    var name = pref("attachmentName", "Reaper: {arxiv_id}").replace("{arxiv_id}", arxivID);
    if (source) name += "_" + source;
    if (light) name += "_light";
    return name;
  }

  var chromeHandle;

  // ──── lifecycle ────────────────────

  async function install() {}
  __name(install, "install");

  async function startup({ id, version, resourceURI, rootURI = resourceURI.spec }) {
    await Zotero.initializationPromise;
    log("startup v" + version);

    chromeHandle = Cc["@mozilla.org/addons/addon-manager-startup;1"]
      .getService(Ci.amIAddonManagerStartup)
      .registerChrome(Services.io.newURI(rootURI + "manifest.json"), [
        ["content", "reaper", rootURI + "content/"],
      ]);

    Zotero.PreferencePanes.register({
      pluginID: id, src: "chrome://reaper/content/preferences.xhtml", label: "Reaper",
    });

    registerMenus(id);
    log("started");
  }
  __name(startup, "startup");

  function registerMenus(id) {
    // ── Item right-click ──
    Zotero.MenuManager.registerMenu({
      menuID: id + "-item-menu", pluginID: id, target: "main/library/item",
      menus: [{
        menuType: "submenu", id: "reaper-item-submenu",
        onShowing: (_e, ctx) => {
          ctx.menuElem.setAttribute("label", "Reaper");
          var items = Zotero.getActiveZoteroPane()?.getSelectedItems() || [];
          ctx.setVisible(items.length > 0 && items.every(function(i) { return i.isRegularItem(); }));
        },
        menus: [
          { menuType: "menuitem",
            onShowing: function(_e, ctx) { ctx.menuElem.setAttribute("label", "Download from Arxiv"); ctx.setVisible(true); },
            onCommand: downloadFromArxivAction },
          { menuType: "menuitem",
            onShowing: function(_e, ctx) { ctx.menuElem.setAttribute("label", "Generate Bilingual HTML"); ctx.setVisible(true); },
            onCommand: generateBilingualAction },
          { menuType: "menuitem",
            onShowing: function(_e, ctx) { ctx.menuElem.setAttribute("label", "Generate Bilingual HTML (Light)"); ctx.setVisible(true); },
            onCommand: generateBilingualLightAction },
          { menuType: "submenu", id: "reaper-source-submenu",
            onShowing: function(_e, ctx) {
              ctx.menuElem.setAttribute("label", "Generate from Source");
              ctx.setVisible(true);
            },
            menus: [
              { menuType: "menuitem",
                onShowing: function(_e, ctx) { ctx.menuElem.setAttribute("label", "arxiv (Full)"); ctx.setVisible(true); },
                onCommand: function() { generateFromSourceAction("arxiv_html"); } },
              { menuType: "menuitem",
                onShowing: function(_e, ctx) { ctx.menuElem.setAttribute("label", "arxiv (Light)"); ctx.setVisible(true); },
                onCommand: function() { generateFromSourceAction("arxiv_html", true); } },
              { menuType: "menuitem",
                onShowing: function(_e, ctx) { ctx.menuElem.setAttribute("label", "ar5iv (Full)"); ctx.setVisible(true); },
                onCommand: function() { generateFromSourceAction("ar5iv"); } },
              { menuType: "menuitem",
                onShowing: function(_e, ctx) { ctx.menuElem.setAttribute("label", "ar5iv (Light)"); ctx.setVisible(true); },
                onCommand: function() { generateFromSourceAction("ar5iv", true); } },
              { menuType: "menuitem",
                onShowing: function(_e, ctx) { ctx.menuElem.setAttribute("label", "ar5ivist (Full)"); ctx.setVisible(true); },
                onCommand: function() { generateFromSourceAction("ar5ivist_docker"); } },
              { menuType: "menuitem",
                onShowing: function(_e, ctx) { ctx.menuElem.setAttribute("label", "ar5ivist (Light)"); ctx.setVisible(true); },
                onCommand: function() { generateFromSourceAction("ar5ivist_docker", true); } },
            ],
          },
        ],
      }],
    });

    // ── Collection right-click (removed) ──

  }

  async function onMainWindowLoad({ window }) {}
  __name(onMainWindowLoad, "onMainWindowLoad");
  async function onMainWindowUnload({ window }) {}
  __name(onMainWindowUnload, "onMainWindowUnload");

  async function shutdown() {
    log("shutdown");
    Zotero.MenuManager.unregisterMenu("reaper@github.io-item-menu");
    if (chromeHandle) { chromeHandle.destruct(); chromeHandle = null; }
  }
  __name(shutdown, "shutdown");
  function uninstall() {}
  __name(uninstall, "uninstall");

  // ──── actions ──────────────────────

  async function downloadFromArxivAction() {
    var zp = Zotero.getActiveZoteroPane(), collection;
    if (!zp) return;
    if (zp.getSelectedCollection) collection = zp.getSelectedCollection();

    var selected = zp.getSelectedItems ? zp.getSelectedItems() : [];

    // Detect arxiv ID from selected items or clipboard
    var prefill = "";
    for (var i = 0; i < selected.length && !prefill; i++) {
      prefill = extractArxivIDFromItem(selected[i]);
    }
    if (!prefill) prefill = (await readClipboard(zp.window)) || "";

    var result = { value: prefill };
    if (!Services.prompt.prompt(zp.window, "Download from Arxiv", "arxiv ID or URL:", result, null, { value: false })) return;
    var arxivID = extractArxivID(result.value);
    if (!arxivID) { zp.window.alert("Reaper: Could not extract arxiv ID."); return; }

    // If items are selected, attach PDF to each
    if (selected.length > 0) {
      for (var i = 0; i < selected.length; i++) {
        var id = extractArxivIDFromItem(selected[i]) || arxivID;
        await attachPDF(selected[i], id);
      }
    } else {
      await importFromArxiv(arxivID, collection);
    }
  }

  async function generateBilingualAction() {
    var zp = Zotero.getActiveZoteroPane(), items;
    if (!zp || !(items = zp.getSelectedItems())) return;
    for (var i = 0; i < items.length; i++) {
      try { await processItem(items[i]); } catch (e) { log("err: " + e); }
    }
  }

  async function generateBilingualLightAction() {
    var zp = Zotero.getActiveZoteroPane(), items;
    if (!zp || !(items = zp.getSelectedItems())) return;
    for (var i = 0; i < items.length; i++) {
      try { await processItem(items[i], true); } catch (e) { log("err: " + e); }
    }
  }

  async function generateFromSourceAction(source, light) {
    var zp = Zotero.getActiveZoteroPane(), items;
    if (!zp || !(items = zp.getSelectedItems())) return;
    for (var i = 0; i < items.length; i++) {
      try { await processItem(items[i], light, source); } catch (e) { log("err: " + e); }
    }
  }

  // ──── arxiv & PDF ──────────────────

  async function importFromArxiv(arxivID, collection) {
    log("Importing " + arxivID);
    flash("Reaper", "Importing " + arxivID + " ...");

    return new Promise(function(resolve, reject) {
      var translate = new Zotero.Translate.Web();
      translate.setHandler("itemDone", async function(obj, item) {
        try {
          await item.saveTx();
          if (collection) { collection.addItem(item.id); await collection.saveTx(); }
          log("Imported: " + item.getField("title"));
        } catch (e) { log("import err: " + e); }
      });
      translate.setHandler("done", function(obj, ok) {
        if (ok) flash("Reaper", "Imported: " + arxivID);
        else flash("Reaper", "Import failed: " + arxivID);
        ok ? resolve() : reject(new Error("failed"));
      });
      translate.setHandler("error", function(e) {
        flash("Reaper", "Import error: " + e);
        reject(e);
      });
      translate.translate({ url: "https://arxiv.org/abs/" + arxivID });
    });
  }

  async function attachPDF(item, arxivID) {
    log("Attaching PDF for " + arxivID);
    flash("Reaper", "Downloading " + arxivID + ".pdf ...");

    try {
      await Zotero.Attachments.importFromURL({
        url: "https://arxiv.org/pdf/" + arxivID + ".pdf",
        parentItemID: item.id,
        title: arxivID + ".pdf",
        contentType: "application/pdf",
      });
      flash("Reaper", "PDF attached: " + arxivID);
      log("PDF attached: " + arxivID);
    } catch (e) {
      flash("Reaper", "PDF download failed: " + e);
      log("PDF attach err: " + e);
    }
  }

  // ──── bilingual HTML ───────────────

  function flash(title, msg) {
    try {
      var pw = new Zotero.ProgressWindow();
      pw.changeHeadline("Reaper");
      pw.addDescription(msg);
      pw.show();
      pw.startCloseTimer(8000);
    } catch (e) {
      try { Services.prompt.alert(null, title, msg); } catch (e2) {}
    }
  }

  async function processItem(item, light, source) {
    if (!item.isRegularItem()) { log("processItem: not a regular item"); return; }
    var arxivID = extractArxivIDFromItem(item);

    if (!arxivID) {
      var zp = Zotero.getActiveZoteroPane();
      var result = { value: "" };
      if (!Services.prompt.prompt(zp.window, "Reaper: No arxiv ID detected",
          "Enter arxiv ID or URL for this item:", result, null, { value: false })) return;
      arxivID = extractArxivID(result.value);
      if (!arxivID) { flash("Reaper", "Could not extract arxiv ID from input."); return; }
    }

    var title = buildTitle(arxivID, source, light);

    // Check if already has a Reaper attachment
    var atts = item.getAttachments();
    var existing = null;
    for (var i = 0; i < atts.length; i++) {
      var att = Zotero.Items.get(atts[i]);
      if (att && att.getField("title") === title) {
        existing = att;
        break;
      }
    }

    if (existing) {
      var zp = Zotero.getActiveZoteroPane();
      var confirmed = zp ? Services.prompt.confirm(
        zp.window,
        "Reaper: Regenerate?",
        "A Reaper attachment already exists for " + arxivID + ".\n\nRegenerate will clear all caches and re-translate. Continue?"
      ) : false;
      if (!confirmed) { log(arxivID + " skipped"); return; }

      // Clear caches via server
      try {
        var clearResp = await fetch(serverURL() + "/api/clear?arxiv_id=" + arxivID);
        log("clear response: " + clearResp.status);
      } catch (e) { log("clear err: " + e); }
    }

    log("Generating " + arxivID + (source ? " from " + source : "") + " via " + serverURL());

    // Show persistent progress window
    var pw;
    try { pw = new Zotero.ProgressWindow(); pw.changeHeadline("Reaper"); pw.addDescription("Translating " + arxivID + " ..."); pw.show(); } catch (e) {}

    var fetchURL = serverURL() + "/api/generate?arxiv_id=" + arxivID;
    if (light) fetchURL += "&embed_images=0";
    if (source) fetchURL += "&source=" + source;

    var html;
    try {
      var resp = await fetch(fetchURL);
      log("fetch status: " + resp.status);
      if (!resp.ok) throw new Error("Server returned " + resp.status);
      html = await resp.text();
      log("fetch done: " + html.length + " bytes");
    } catch (e) {
      log("fetch FAIL: " + e + " (url: " + fetchURL + ")");
      var msg = String(e).indexOf("NetworkError") !== -1 || String(e).indexOf("fetch") !== -1
        ? "Cannot connect to " + serverURL() + ". Make sure the Reaper server is running."
        : "Error: " + e;
      if (pw) { pw.addDescription(msg); pw.startCloseTimer(10000); }
      else { flash("Reaper", msg); }
      return;
    }

    // Save attachment — write to temp file, then import into Zotero storage
    flash("Reaper", "Saving " + title + " ...");

    try {
      var tmpDir = Zotero.getTempDirectory().path;
      var tmpFile = tmpDir + arxivID + "_reaper.html";
      await Zotero.File.putContentsAsync(tmpFile, html);

      var att = await Zotero.Attachments.importFromFile({
        file: tmpFile,
        parentItemID: item.id,
        title: title,
        contentType: "text/html",
      });
      log("imported attachment id: " + (att ? att.id : "null"));
    } catch (e) {
      log("save err: " + e);
      flash("Reaper", "Failed to save: " + e);
      return;
    }

    flash("Reaper", "Saved: " + title);
    log("Saved: " + title);
  }

  // ──── utils ────────────────────────

  function extractArxivID(input) {
    var m;
    if ((m = input.match(/^(\d{4}\.\d{4,5})(v\d+)?$/))) return m[1] + (m[2] || "");
    if ((m = input.match(/arxiv\.org\/abs\/(\d{4}\.\d{4,5}(?:v\d+)?)/))) return m[1];
    if ((m = input.match(/arxiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)/i))) return m[1];
    return null;
  }

  async function readClipboard(w) {
    try { var t = await navigator.clipboard.readText(); if (t) return extractArxivID(t) || t.trim().substring(0, 200); } catch (e) {}
    return "";
  }

  function extractArxivIDFromItem(item) {
    var m, u = item.getField("url");
    if (u && (m = u.match(/arxiv\.org\/abs\/(\d{4}\.\d{4,5}(?:v\d+)?)/))) return m[1];
    var e = item.getField("extra");
    if (e && (m = e.match(/arxiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)/i))) return m[1];
    var d = item.getField("DOI");
    if (d && (m = d.match(/10\.48550\/arxiv\.(\d{4}\.\d{4,5}(?:v\d+)?)/i))) return m[1];
    return null;
  }

  return { install, onMainWindowLoad, onMainWindowUnload, shutdown, startup, uninstall };
})();
