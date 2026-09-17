struct Params { v: array<vec4<f32>, 16> }
@group(0) @binding(0) var<uniform> p: Params;
@group(0) @binding(1) var source: texture_2d<f32>;
@group(0) @binding(2) var source_sampler: sampler;
struct Vertex { @builtin(position) position:vec4<f32>, @location(0) uv:vec2<f32> }
@vertex fn vs(@builtin(vertex_index) i:u32)->Vertex {
    var positions=array<vec2<f32>,3>(vec2(-1.,-1.),vec2(3.,-1.),vec2(-1.,3.));
    let point=positions[i]; var out:Vertex;out.position=vec4(point,0.,1.);out.uv=vec2(point.x*.5+.5,.5-point.y*.5);return out;
}
fn rotate(q:vec4<f32>,v:vec3<f32>)->vec3<f32> {return v+2.*cross(q.xyz,cross(q.xyz,v)+q.w*v);}
fn ray_at(uv:vec2<f32>)->vec3<f32> {
    let xy=vec2(2.*uv.x-1.,1.-2.*uv.y);let aspect=p.v[1].x/p.v[1].y;let f=p.v[1].z;
    var ray:vec3<f32>;
    if p.v[1].w<.5 {ray=normalize(vec3(xy.x*tan(f*.5),xy.y*tan(f*.5)/aspect,-1.));}
    else if p.v[1].w<1.5 {let a=xy*vec2(1.,1./aspect)*2.*tan(f*.25);let r=dot(a,a);ray=vec3(4.*a,r-4.)/(r+4.);}
    else {let lon=xy.x*3.14159265359;let lat=xy.y*1.57079632679;ray=vec3(sin(lon)*cos(lat),sin(lat),-cos(lon)*cos(lat));}
    return rotate(p.v[0],ray);
}
fn lens(ray:vec3<f32>,i:u32)->vec4<f32> {
    let base=6u+3u*i;let r=vec3(dot(p.v[base].xyz,ray),dot(p.v[base+1u].xyz,ray),dot(p.v[base+2u].xyz,ray));
    let radial=length(r.xy);let theta=atan2(radial,r.z);let max_theta=p.v[12u+i].x;
    if theta>max_theta || (radial<.000001 && r.z<0.) {return vec4(0.);}
    let t=theta*theta;let d=p.v[4u+i];let td=theta*(1.+t*(d.x+t*(d.y+t*(d.z+t*d.w))));
    var scale=1.;if radial>.000001 {scale=td/radial;}
    let k=p.v[2u+i];let uv=vec2(k.x*r.x*scale+p.v[14u+i].x*r.y*scale+k.z,k.y*r.y*scale+k.w);
    if any(uv<vec2(0.)) || any(uv>vec2(1.)) {return vec4(0.);}
    let edge=clamp(min(min(uv.x,1.-uv.x),min(uv.y,1.-uv.y))/.04,0.,1.);
    let weight=max(.001,edge*clamp((max_theta-theta)/.25,0.,1.));
    let dims=vec2<f32>(textureDimensions(source));
    // Clamp within each half to prevent bilinear sampling across the packed boundary.
    let sample_uv=vec2(clamp((uv.x+f32(i))*.5,(f32(i)*dims.x*.5+.5)/dims.x,((f32(i)+1.)*dims.x*.5-.5)/dims.x),clamp(uv.y,.5/dims.y,1.-.5/dims.y));
    let rgb=textureSampleLevel(source,source_sampler,sample_uv,0.).rgb*p.v[12u+i].yzw;
    return vec4(rgb*weight,weight);
}
fn color_at(uv:vec2<f32>)->vec3<f32> {let ray=ray_at(uv);let a=lens(ray,0u);let b=lens(ray,1u);return (a.rgb+b.rgb)/max(a.a+b.a,.000001);}
@fragment fn fs(in:Vertex)->@location(0) vec4<f32> {
    if p.v[14].y>.5 {let d=vec2(.25/p.v[1].x,.25/p.v[1].y);return vec4((color_at(in.uv+d)+color_at(in.uv-d)+color_at(in.uv+vec2(d.x,-d.y))+color_at(in.uv+vec2(-d.x,d.y)))*.25,1.);}
    return vec4(color_at(in.uv),1.);
}
