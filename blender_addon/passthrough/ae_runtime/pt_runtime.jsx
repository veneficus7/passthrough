/*
 * Passthrough ExtendScript runtime.
 *
 * Concatenated into every generated .jsx by jsx_writer.py.
 *
 * ECMAScript 3 ONLY (SPEC.md 7.1). Not available here, and some of these fail
 * silently rather than loudly:
 *   let, const, arrow functions, template literals,
 *   JSON.parse / JSON.stringify,
 *   Array.prototype.forEach / map / filter / indexOf,
 *   String.prototype.trim, Object.keys
 * Use var, function () {}, string concatenation and indexed for loops.
 */

function ptFindComp(name) {
    var items = app.project.items;
    var i;
    for (i = 1; i <= items.length; i++) {
        if (items[i] instanceof CompItem && items[i].name === name) {
            return items[i];
        }
    }
    return null;
}

/*
 * Reuse a comp of the same name rather than piling up duplicates every time
 * the script is run, mirroring the idempotency the Blender side has.
 */
function ptEnsureComp(name, width, height, pixelAspect, duration, frameRate) {
    var comp = ptFindComp(name);
    if (comp === null) {
        return app.project.items.addComp(name, width, height, pixelAspect, duration, frameRate);
    }
    comp.width = width;
    comp.height = height;
    comp.pixelAspect = pixelAspect;
    comp.duration = duration;
    comp.frameRate = frameRate;
    return comp;
}

function ptRemoveLayer(comp, name) {
    var i;
    for (i = comp.numLayers; i >= 1; i--) {
        if (comp.layer(i).name === name) {
            comp.layer(i).remove();
        }
    }
}

/*
 * One value means a static property; more means a keyframed one. Writing a
 * single setValue avoids littering the timeline with identical keys.
 */
function ptApply(prop, times, values) {
    if (values.length === 0) {
        return;
    }
    if (values.length === 1) {
        prop.setValue(values[0]);
        return;
    }
    prop.setValuesAtTimes(times, values);
}

function ptAddCamera(comp, name, times, positions, orientations, zooms) {
    ptRemoveLayer(comp, name);
    var cam = comp.layers.addCamera(name, [comp.width / 2, comp.height / 2]);
    cam.autoOrient = AutoOrientType.NO_AUTO_ORIENT;
    ptApply(cam.property("Position"), times, positions);
    ptApply(cam.property("Orientation"), times, orientations);
    ptApply(cam.property("Zoom"), times, zooms);
    return cam;
}
