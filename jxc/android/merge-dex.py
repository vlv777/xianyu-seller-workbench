import shutil
import sys
import zipfile

base, dex, out = sys.argv[1], sys.argv[2], sys.argv[3]
shutil.copyfile(base, out)
with zipfile.ZipFile(out, 'a') as z:
    z.write(dex, 'classes.dex')
print('merged ->', out)
