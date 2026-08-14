#!/usr/bin/env python3
"""Pure in-memory threat model for the V41 interface. This is not an executor."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import PurePosixPath

BRANCH_ROOTS={"AUTHORIZATION":PurePosixPath("workflow/approvals"),"FORMAL_MEMORY_UPDATE_EVENT":PurePosixPath("workflow/claude_writer_agent/formal_memory_updates")}

@dataclass
class ModelState:
 ledger:list[str]=field(default_factory=list)
 targets:dict[str,str]=field(default_factory=dict)
 authority_consumed:bool=False
 journal:str|None=None
 lock:bool=False
 receipt:dict|None=None

def normalized(path:str)->PurePosixPath|None:
 p=PurePosixPath(path)
 if p.is_absolute() or '..' in p.parts or '.' in p.parts:return None
 return p

def validate(branch:str,ledger_path:str,target_path:str,symlinks:set[str],write_targets:list[str])->list[str]:
 f=[];root=BRANCH_ROOTS.get(branch);lp=normalized(ledger_path);tp=normalized(target_path)
 if root is None:f.append('WRONG_BRANCH')
 if lp!=PurePosixPath('workflow/nonce_ledgers/E40_U18_NONCE_LEDGER.json'):f.append('NONCE_LEDGER_PATH_NOT_EXACT')
 if tp is None or root is None or root not in tp.parents:f.append('TARGET_PATH_ESCAPE_OR_WRONG_BRANCH')
 if ledger_path in symlinks or target_path in symlinks:f.append('SYMLINK_REJECTED')
 if len(write_targets)!=2 or set(write_targets)!={ledger_path,target_path}:f.append('SECOND_OR_MISSING_TARGET_REJECTED')
 return sorted(set(f))

def run_model(branch:str,nonce:str,ledger_path:str,target_path:str,*,symlinks:set[str]|None=None,write_targets:list[str]|None=None,crash_at:str|None=None)->dict:
 """Simulate only; returned state has no relationship to disk."""
 symlinks=symlinks or set();write_targets=write_targets or [ledger_path,target_path];state=ModelState();before=(list(state.ledger),dict(state.targets),state.authority_consumed)
 failures=validate(branch,ledger_path,target_path,symlinks,write_targets)
 if failures:return {'status':'FAIL_CLOSED_NO_CHANGE','failures':failures,'state':state,'recoverable':True}
 state.lock=True;state.journal='PREPARED'
 if nonce in state.ledger:return {'status':'FAIL_CLOSED_NO_CHANGE','failures':['NONCE_REPLAY_RACE'],'state':state,'recoverable':True}
 staged_ledger=state.ledger+[nonce];state.journal='NONCE_STAGED'
 if crash_at=='NONCE_STAGED':return recover(state,before,staged_ledger,target_path,nonce,crash_at)
 staged_target='EXACT_BRANCH_PAYLOAD';state.journal='TARGET_STAGED'
 if crash_at=='TARGET_STAGED':return recover(state,before,staged_ledger,target_path,nonce,crash_at)
 state.ledger=staged_ledger;state.targets[target_path]=staged_target
 if crash_at=='ONE_SIDE_INSTALLED':
  state.targets.pop(target_path)
  return recover(state,before,staged_ledger,target_path,nonce,crash_at)
 state.authority_consumed=True;state.journal='COMMITTED';state.receipt={'nonce':nonce,'branch':branch,'ledger_post':'MODEL_SHA','target_post':'MODEL_SHA','single_use_authority_consumed':True};state.lock=False
 return {'status':'MODEL_COMMIT_COMPLETE_NOT_EXECUTED','failures':[],'state':state,'recoverable':True}

def recover(state:ModelState,before:tuple,target_ledger:list[str],target_path:str,nonce:str,crash_at:str)->dict:
 """Model deterministic recovery: restore both before-images for any injected partial crash."""
 state.ledger=list(before[0]);state.targets=dict(before[1]);state.authority_consumed=before[2];state.journal='ROLLED_BACK';state.lock=False;state.receipt=None
 return {'status':'MODEL_CRASH_RECOVERED_BOTH_UNCHANGED','failures':[f'INJECTED_CRASH:{crash_at}'],'state':state,'recoverable':state.ledger==before[0] and state.targets==before[1] and state.authority_consumed==before[2]}
