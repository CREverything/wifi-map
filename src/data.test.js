import test from 'node:test';
import assert from 'node:assert/strict';
import {validateModelResponse,demo} from './data.js';
test('accepts valid and empty model results',()=>{assert.deepEqual(validateModelResponse(demo),demo);assert.deepEqual(validateModelResponse({version:1,summary:'No areas',areas:[]}).areas,[]);});
test('rejects invalid model fields',()=>{for(const change of [{latitude:91},{intensity:2},{radiusMeters:-1},{longitude:'0'},{explanation:null}])assert.throws(()=>validateModelResponse({...demo,areas:[{...demo.areas[0],...change}]}));});
test('rejects prose and unsupported versions',()=>{for(const value of ['Here is your map',null,{...demo,version:2}])assert.throws(()=>validateModelResponse(value));});
