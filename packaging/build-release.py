#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build separate runtime and corresponding-source packages from committed files."""
import argparse,hashlib,json,re,runpy,shutil,subprocess,tarfile,tempfile,time,zipfile
from pathlib import Path,PurePosixPath

GRAPHICS_BASE_SHA256='6ddc1e4dbf0c5663d2ed70df3c6eed406211cffad6c0f406f53c2e87b236d9dd'
RUNTIME_ROOT={'install.sh','uninstall.sh','MWM.py','README.md','LICENSE'}
HELPERS={'packaging/ubuntu-build-sdk.py','packaging/ubuntu-safe-apt.sh','packaging/apt_guard.py','packaging/mwm-root-helper','packaging/mwm-waydroid-backup.py','packaging/mwm_targeted_backup.py','packaging/ubuntu-host.sh','packaging/build-ubuntu-mangoapp.sh'}
USER_DOCS={'docs/SETUP.md','docs/RTSCALE.md'}
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def runtime_file(name):
    if name.startswith('packaging/payload/sources/'):return False
    if name.startswith('mwm/vendor/mangoapp/') and (name.endswith(('.tar.gz','.patch','.h')) or name.endswith('/BUILD.md')):return False
    if name.startswith('mwm/') and name.endswith(('.c','.h','.cpp')):return False
    return name in RUNTIME_ROOT or name in HELPERS or name in USER_DOCS or name.startswith(('docs/images/readme/','mwm/','LICENSES/','packaging/payload/'))
def source_file(name):
    if name=='mwm/scripts/mangoapp-bin/mangoapp':return True
    if name in RUNTIME_ROOT or name=='packaging/anonymize-build-paths.py' or name in USER_DOCS or name in HELPERS:return True
    if name.startswith(('LICENSES/','docs/images/readme/','docs/graphics/','packaging/tests/graphics/','packaging/payload/manifests/')):return True
    return name.startswith('mwm/') and not name.startswith(('mwm/scripts/mangoapp-native/','mwm/scripts/mangoapp-bin/'))
def add_bytes(archive,name,data,timestamp,mode=0o644):
    import io
    info=tarfile.TarInfo(name);info.size=len(data);info.mtime=timestamp;info.mode=mode
    info.uid=info.gid=0;info.uname=info.gname='root';archive.addfile(info,io.BytesIO(data))
def compress_zstd(source,target):
    try:import zstandard
    except ImportError:
        if not shutil.which('zstd'):raise RuntimeError('Install zstd or Python zstandard to build sources')
        subprocess.run(['zstd','-T0','-19','-q',str(source),'-o',str(target)],check=True)
    else:
        with source.open('rb') as src,target.open('wb') as out:zstandard.ZstdCompressor(level=19).copy_stream(src,out)
def build(repo,out,graphics,label):
    if label!='release' and not re.fullmatch(r'rc[1-9][0-9]*',label):raise ValueError('Use rcN or release')
    subprocess.run(['git','diff','--exit-code','HEAD'],cwd=repo,check=True,stdout=subprocess.DEVNULL)
    if subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=repo,text=True).strip():raise ValueError('Commit new source before packaging')
    if digest(graphics)!=GRAPHICS_BASE_SHA256:raise ValueError('Unexpected graphics base source archive')
    payload=repo/'packaging/payload'
    for line in (payload/'SHA256SUMS').read_text(encoding='utf8').splitlines():
        value,name=line.split(maxsplit=1)
        if digest(payload/name.lstrip('*'))!=value:raise ValueError('Payload checksum mismatch: '+name)
    version=runpy.run_path(str(repo/'mwm/version.py'))['__version__']
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    timestamp=int(subprocess.check_output(['git','show','-s','--format=%ct','HEAD'],cwd=repo,text=True))
    prefix=f'MLTD_Waydroid_Manager_v{version}'+('' if label=='release' else '-'+label)
    out.mkdir(parents=True,exist_ok=True);runtime=out/(prefix+'.zip');sources=out/(prefix+'_sources.tar.zst')
    if runtime.exists() or sources.exists() or (out/'SHA256SUMS').exists():raise ValueError('Output already exists')
    stages=subprocess.check_output(['git','ls-files','--stage'],cwd=repo,text=True).splitlines()
    files={line.split('\t',1)[1]:int(line.split()[0],8) for line in stages}
    for name in files:
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or any(x in p.parts for x in ('.git','__pycache__','updates','investigations')):raise ValueError('Unexpected tracked file: '+name)
    manifest={'version':version,'candidate':label,'source_commit':commit,'graphics_base_sha256':GRAPHICS_BASE_SHA256,
        'sources_archive':sources.name,'graphics_base_requires_patches':['docs/graphics/msaa/mesa-msaa-storage2.patch','docs/graphics/depth-blit/mesa-depth-only-blit.patch','docs/graphics/half-height/mesa-rtscale-half-height.patch'],
        'payload_sha256_file':'packaging/payload/SHA256SUMS'}
    encoded=(json.dumps(manifest,indent=2)+'\n').encode()
    with zipfile.ZipFile(runtime,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,mode in files.items():
            if not runtime_file(name):continue
            info=zipfile.ZipInfo(prefix+'/'+name,time.gmtime(max(timestamp,315532800))[:6]);info.create_system=3;info.external_attr=mode<<16
            info.compress_type=zipfile.ZIP_STORED if name.endswith(('.zst','.gz')) else zipfile.ZIP_DEFLATED
            archive.writestr(info,(repo/name).read_bytes())
        info=zipfile.ZipInfo(prefix+'/packaging/RELEASE_MANIFEST.json');info.create_system=3;info.external_attr=0o100644<<16;archive.writestr(info,encoded)
        if archive.testzip():raise ValueError('ZIP integrity failure')
        if not (archive.getinfo(prefix+'/install.sh').external_attr>>16)&0o111:raise ValueError('Lost installer executable permission')
        for entry in archive.namelist():
            relative=entry.removeprefix(prefix+'/')
            if relative.startswith(('packaging/tests/','docs/graphics/')) or relative.endswith(('build-release.py','check-release.py')):raise ValueError('Development file in runtime ZIP')
    with tempfile.TemporaryDirectory() as temporary:
        tarpath=Path(temporary)/'sources.tar'
        with tarfile.open(tarpath,'w') as archive:
            base=tarfile.TarInfo(prefix+'_sources/graphics-sources.tar.zst');base.size=graphics.stat().st_size;base.mtime=timestamp;base.mode=0o644;base.uname=base.gname='root'
            with graphics.open('rb') as stream:archive.addfile(base,stream)
            for name,mode in files.items():
                if source_file(name):add_bytes(archive,prefix+'_sources/'+name,(repo/name).read_bytes(),timestamp,mode&0o777)
            add_bytes(archive,prefix+'_sources/BUILD.md',(repo/'packaging/source-build.md').read_bytes(),timestamp)
            add_bytes(archive,prefix+'_sources/SOURCE_MANIFEST.json',encoded,timestamp)
        compress_zstd(tarpath,sources)
    (out/'SHA256SUMS').write_text(''.join(digest(p)+'  '+p.name+'\n' for p in (runtime,sources)),encoding='ascii')
    print(json.dumps({'runtime':str(runtime),'sources':str(sources),'source_commit':commit}))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--graphics-sources',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--label',default='rc1');args=parser.parse_args()
    build(Path(__file__).resolve().parents[1],args.output.resolve(),args.graphics_sources.resolve(),args.label)
