import test from 'node:test';
import assert from 'node:assert/strict';
import { changeEffect } from '../src/changes.ts';
import { emptyConfig } from '../src/types.ts';

const config = () => ({...emptyConfig(), widgets: [{id:'map', type:'map', x:0,y:0,w:6,h:5,
  title:'Sites',color:'#0069b4',lat_field:'lat',lon_field:'lon',y_field:'value',aggregate:'avg'}],
  filters:[{field:'country',type:'category',label:'Country'}]});
test('appearance, layout, labels and their undo do not request data', () => {
  const before=config(), after=structuredClone(before);
  after.style={...before.style,theme:'dark',background:'#123456'};
  Object.assign(after.widgets[0], {x:2,w:8,color:'#ffcc00',title:'Locations',show_legend:false});
  after.filters[0].label='Place';
  assert.equal(changeEffect(before,after),'visual');
  assert.equal(changeEffect(after,before),'visual');
});
test('aggregation, map coordinates, blocks and facets need a query', () => {
  for (const modify of [c=>c.widgets[0].aggregate='max',c=>c.widgets[0].lat_field='other',
    c=>c.widgets.push({...c.widgets[0],id:'second'}),c=>c.filters[0].field='site']) {
    const before=config(), after=structuredClone(before); modify(after);
    assert.equal(changeEffect(before,after),'query');
    assert.equal(changeEffect(after,before),'query');
  }
});
test('source interpretation requires a profile even alongside visual edits', () => {
  const before=config(), after=structuredClone(before);
  after.source.types.value='number'; after.style.theme='dark';
  assert.equal(changeEffect(before,after),'source');
});
