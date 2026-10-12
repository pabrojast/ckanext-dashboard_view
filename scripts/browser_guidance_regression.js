// Local synthetic-data checks for editor guidance, validation and keyboard use.
async (page) => {
  const base = new URL(page.url());
  if (!['127.0.0.1', 'localhost'].includes(base.hostname)) throw Error('Local fixture required');
  const check = (value, message) => { if (!value) throw Error(message); };
  await page.goto(new URL('/edit?lang=es',base).href,{waitUntil:'domcontentloaded'});
  await page.setViewportSize({width:1440,height:1000});
  const root = page.locator('[data-dashboard]');
  const ready = () => page.locator('.dbv-canvas[aria-busy="false"]').waitFor();
  const config = () => page.locator('input[name=dashboard_config]').inputValue().then(JSON.parse);
  await ready();
  let dataRequests = 0, saves = 0;
  const listener = request => {
    if (/\/dashboard-api\/.*\/(profile|query)$/.test(request.url())) dataRequests++;
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/save') saves++;
  };
  page.on('request',listener);
  const header = page.locator('[data-widget-id="records"] .dbv-widget-header');
  await header.focus(); await header.press('Shift+ArrowRight');
  await page.waitForTimeout(500);
  const serialized = await config();
  const actual = await page.locator('.grid-stack-item').evaluateAll(items => items.map(item => ({
    id:item.dataset.widgetId, x:Number(item.getAttribute('gs-x')||0), y:Number(item.getAttribute('gs-y')||0),
    w:Number(item.getAttribute('gs-w')||1), h:Number(item.getAttribute('gs-h')||1),
  })));
  for (const node of actual) {
    const widget = serialized.widgets.find(w => w.id === node.id);
    check(['x','y','w','h'].every(key => widget[key] === node[key]), 'Collision-resolved layout must be saved');
  }
  check(dataRequests === 0,'Keyboard layout edit must not query data');
  await page.getByRole('button',{name:'Deshacer',exact:true}).click();
  await page.locator('[data-widget-id="trend"]').getByRole('button',{name:'Configurar',exact:true}).click();
  await page.locator('.dbv-inspector [data-property="x_field"]').selectOption('');
  await page.waitForTimeout(400); await ready();
  await root.getByRole('button',{name:'Guardar dashboard',exact:true}).click();
  check(saves === 0,'Invalid block must not submit form');
  check(await page.locator('.dbv-inspector [data-property="x_field"]').getAttribute('aria-invalid') === 'true','Invalid field annotated');
  check(await page.locator('.dbv-inspector [data-property="x_field"]').evaluate(el => el === document.activeElement),'Invalid field focused');
  await page.screenshot({path:'output/playwright/appearance-validation.png'});
  await page.locator('.dbv-inspector [data-property="x_field"]').selectOption('date');
  await page.waitForTimeout(400); await ready();
  await page.locator('[data-widget-id="countries"] .dbv-chart-data summary').click();
  const category = page.locator('[data-widget-id="countries"]').getByRole('button',{name:'Filtrar: Chile',exact:true});
  await category.focus(); await category.press('Enter'); await ready();
  check(await page.getByRole('combobox',{name:'País',exact:true}).inputValue() === JSON.stringify('Chile'),'Keyboard chart action applies typed filter');
  await page.getByRole('button',{name:'Limpiar filtros',exact:true}).click(); await ready();
  await page.getByRole('button',{name:'Filtrar por esta zona del mapa',exact:true}).click(); await ready();
  const style = (await config()).style;
  await page.getByRole('button',{name:'2. Elegir bloques',exact:true}).click();
  await page.getByRole('button',{name:'En el tiempo',exact:true}).click();
  await page.getByRole('combobox',{name:'Variable principal',exact:true}).selectOption('temperature');
  check((await page.locator('.dbv-template-fields').textContent()).includes('temperature'),'Template previews chosen variable');
  // The native replacement prompt is already covered manually; this fixture is disposable.
  await page.evaluate(() => { window.confirm = () => true; });
  await page.getByRole('button',{name:'Aplicar plantilla',exact:true}).click();
  await page.waitForTimeout(400); await ready();
  const updated = await config();
  check(updated.widgets.filter(w => w.type === 'kpi' && w.aggregate !== 'count').every(w => w.y_field === 'temperature'),'Template uses selected value');
  check(JSON.stringify(updated.style) === JSON.stringify(style),'Template retains appearance');
  check(await page.locator('.dbv-status.is-error:visible').count() === 0,'Template clears stale map bounds');
  page.off('request',listener);
  return {keyboardCollisionLayout:true,visualQueries:0,invalidSaveBlocked:true,invalidFieldFocused:true,keyboardChartFilter:true,templateVariable:true,templateClearsMapBounds:true};
}
