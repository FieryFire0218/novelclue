// Use a normal extension tab: the file picker cannot unload it like a popup.
let collectorTabId = null;
let opening = false;
browser.browserAction.onClicked.addListener(async () => {
  if (opening) return;
  opening = true;
  try {
    if (collectorTabId !== null) {
      try {
        await browser.tabs.update(collectorTabId, {active: true});
        return;
      } catch (_) { collectorTabId = null; }
    }
    const tab = await browser.tabs.create({url: browser.runtime.getURL('popup.html'), active: true});
    collectorTabId = tab.id;
  } finally { opening = false; }
});
browser.tabs.onRemoved.addListener(id => { if (id === collectorTabId) collectorTabId = null; });
