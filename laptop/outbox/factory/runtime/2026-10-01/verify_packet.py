"""Offline verification of this sanitized packet; no execution or network access."""
import hashlib,json,re
from pathlib import Path

root=Path(__file__).resolve().parent
digest=lambda b:hashlib.sha256(b).hexdigest()
load=lambda file:json.loads((root/file).read_bytes())
count=0
def verify(value,description):
 global count
 if not value: raise SystemExit('FAIL: '+description)
 count+=1

expected_files=set()
for row in (root/'SHA256SUMS').read_text().splitlines():
 expected,name=row.split('  ',1)
 file=(root/name).resolve()
 verify(file.is_relative_to(root) and file.is_file(),'manifest member')
 verify(digest(file.read_bytes())==expected,'export content hash: '+name)
 expected_files.add(name)
verify(expected_files=={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='SHA256SUMS'},'exact file set')
packet=load('packet.json');passed=0
verify(packet['schema']=='factory.sanitized-runtime-packet.v1','packet schema')
verify(packet['runtime']=={'platform':'linux','node':'v22.16.0'},'qualified runtime')
recipes={r['id']:r for r in load('qualification-manifest.json')['recipes']}
source={r['file']:r for r in load('source-hashes.json')['files']}
intervals=[]
from datetime import datetime
for item in packet['jobs']:
 record=load(item['record']);job=record['job'];execution=record['execution'];receipt=load('jobs/'+job['id']+'/verification.json')
 fingerprint=digest(json.dumps({k:v for k,v in job.items() if k!='fingerprint'},separators=(',',':'),ensure_ascii=False).encode())
 verify(fingerprint==item['fingerprint']==job['fingerprint']==execution['jobFingerprint']==receipt['jobFingerprint'],'job correlation')
 verify(record['sourceSchema']=='factory.execution-record.v1' and record['schema']=='factory.sanitized-execution-record.v1','record schemas')
 verify(record['verification']==receipt and receipt['passed'] is True,'preserved verification')
 verify(receipt['artifactDigest']==record['result']['artifactDigest']==execution['stdoutSha256']==record['exportedArtifacts']['originalStdoutSha256'],'original output digest correlation')
 verify(execution['exitCode']==0 and execution['executionClosed'] is True and execution['stopReason'] is None,'closed successful execution')
 verify(receipt['verifierId']!=execution['executorId'],'separate verifier identity')
 verify(record['status']=='succeeded' and record['attempts']==1,'ledger final status')
 timeline=record['statusTimeline']
 verify([e['status'] for e in timeline]==['queued','running','verifying','succeeded'],'status timeline')
 verify([e['at'] for e in timeline]==sorted(e['at'] for e in timeline),'timeline order')
 verify(execution['sourceManifest']==recipes[job['id']]['manifest'],'reviewed recipe manifest')
 for row in execution['sourceManifest']:
  verify(source[row['file']]['sha256']==row['sha256'],'canonical source hash')
 stdout=(root/record['exportedArtifacts']['stdout']).read_bytes()
 verify(digest(stdout)==record['exportedArtifacts']['exportedStdoutSha256'],'sanitized output digest')
 totals={k:int(re.findall(r'^# '+k+r' (\d+)$',stdout.decode(),re.M)[-1]) for k in ('tests','pass','fail','cancelled','skipped','todo')}
 verify(totals==receipt['summary'] and totals['tests']==totals['pass']==execution['expectedTests'],'sanitized TAP totals')
 verify(all(totals[k]==0 for k in ('fail','cancelled','skipped','todo')),'no unsuccessful tests')
 verify(len(re.findall(rb'^ok \d+ - label omitted$',stdout,re.M))==totals['tests'],'individual passing TAP rows')
 verify((root/record['exportedArtifacts']['stderr']).read_bytes()==b'','empty stderr')
 passed+=totals['pass']
 intervals.append([datetime.fromisoformat(execution[k].replace('Z','+00:00')) for k in ('startedAt','completedAt')])
verify(passed==68==packet['testsPassed'],'68 tests passed')
verify(round((min(x[1] for x in intervals)-max(x[0] for x in intervals)).total_seconds()*1000)==packet['parallelOverlapMs']==217,'217 ms overlap')
verify(load('export-validation.json')['allPassed'] and load('export-validation.json')['checkCount']==64,'export readback record')
verify(packet['delivery']['medicAcceptance']=='not established','acceptance boundary')
for p in root.rglob('*'):
 if not p.is_file() or p.suffix=='.py': continue
 text=p.read_text()
 verify(not re.search(r'(?i)(?<![a-z])[a-z]:[\\/]|/(?:mnt|home|tmp|Users|root)/|LAPTOP-[A-Z0-9]+|github_pat_|gh[pousr]_[A-Za-z0-9]{10}|sk-proj-|Bearer\s|https?://[^\s]*[?&](?:token|sig|key)=',text),'privacy scan: '+p.name)
verify(all('pid' not in load(item['record'])['execution'] for item in packet['jobs']),'process identifiers omitted')
print(json.dumps({'allPassed':True,'checksPassed':count,'testsRepresented':passed,'newExecutions':0},indent=2))
