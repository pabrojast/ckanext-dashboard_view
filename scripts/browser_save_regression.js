// Pass this function to `playwright-cli run-code` on scripts/dev_server.py.
// Uses only the localhost fixture: never writes a shared CKAN environment.
async (page) => {
  const base = new URL(page.url());
  if (!['127.0.0.1', 'localhost'].includes(base.hostname))
    throw new Error('Run this regression against the local dashboard harness.');
  const edit = new URL('/edit?lang=en', base).href;
  const view = new URL('/dashboard/demo', base).href;
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  await page.goto(edit);
  const bootstrap = async () => JSON.parse(await page.locator('[data-dashboard-bootstrap]').textContent());
  const original = await bootstrap();
  let posts = 0;
  const countSave = (request) => {
    if (request.method() === 'POST' && request.url() === new URL('/save', base).href) posts++;
  };
  page.on('request', countSave);
  const saveOnce = async (field) => {
    check(await field.evaluate(element => document.activeElement === element), 'Input must still have focus');
    const before = posts;
    // Deliberately no Tab, blur or second click: this is the reported failure.
    await page.getByRole('button', {name: 'Save dashboard', exact: true}).click();
    await page.waitForURL(view, {timeout: 5000});
    check(posts === before + 1, 'Exactly one native form POST is required');
    await page.goto(edit);
  };
  try {
    for (const [width, title] of [[1440, 'Single-click save regression'], [390, original.config.widgets[0].title]]) {
      await page.setViewportSize({width, height: 1000});
      await page.getByRole('button', {name: 'Configure', exact: true}).first().click();
      const field = page.getByRole('textbox', {name: 'Title', exact: true});
      await field.fill(title);
      await saveOnce(field);
      check((await bootstrap()).config.widgets[0].title === title, 'Block title must survive reopening');
    }
    await page.setViewportSize({width: 1440, height: 1000});
    for (const title of ['Focused dashboard title', original.title]) {
      const field = page.getByRole('textbox', {name: 'Título', exact: true});
      await field.fill(title);
      await saveOnce(field);
      check((await bootstrap()).title === title, 'Dashboard title must survive reopening');
    }
    check(posts === 4, 'Expected four successful single-click saves');
    await page.getByRole('button', {name: 'Configure', exact: true}).first().click();
    const field = page.getByRole('textbox', {name: 'Title', exact: true});
    await field.fill('Undo and redo regression');
    await field.press('Tab');
    const undo = page.getByRole('button', {name: 'Undo', exact: true});
    const redo = page.getByRole('button', {name: 'Redo', exact: true});
    check(await undo.isEnabled(), 'Undo state must update without replacing its button');
    await undo.click();
    check(await redo.isEnabled(), 'Redo state must update after Undo');
    await redo.click();
    await page.getByRole('heading', {name: 'Undo and redo regression', exact: true}).waitFor();
    await undo.click();
    await page.getByRole('heading', {name: original.config.widgets[0].title, exact: true}).waitFor();
  } finally {
    page.off('request', countSave);
  }
}
