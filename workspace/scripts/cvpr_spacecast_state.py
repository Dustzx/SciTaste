"""Conservative dependency invalidation for model-proposed BEFORE-scene facts.

The tool adds no observations, answers, inferred 3D coordinates or post-edit
images. These rules are a hypothesis to evaluate, not verified spatial truth.
"""
import copy
import re


def entity(value):
    # Determiners are surface syntax, not a different physical object.
    return re.sub(r'^(?:the|an|a)\s+', '', str(value).strip().lower())


def invalidate(graph):
    if not isinstance(graph,dict):return graph,{'status':'unsupported'}
    result=copy.deepcopy(graph);edit=result.get('intervention',{});facts=result.get('facts',[])
    kinds={'none','object_move','object_rotate','object_remove','frame_rotate'}
    if not isinstance(edit,dict) or edit.get('kind') not in kinds or not isinstance(facts,list) or len(facts)>24:
        return graph,{'status':'unsupported'}
    targets=edit.get('targets',[])
    if not isinstance(targets,list) or any(not isinstance(x,str) for x in targets):return graph,{'status':'unsupported'}
    targets={entity(x) for x in targets};changed=[]
    kind=edit['kind'];frame=edit.get('frame')
    if kind=='frame_rotate' and frame not in {'camera','world','object'}:return graph,{'status':'unsupported'}
    if kind.startswith('object_') and not targets:return graph,{'status':'unsupported'}
    for i,fact in enumerate(facts):
        if not isinstance(fact,dict) or fact.get('frame') not in {'camera','world','object','invariant','unknown'}:
            return graph,{'status':'unsupported'}
        names={entity(fact.get(k,'')) for k in ['subject','object']}
        owner=entity(fact.get('frame_owner',''))
        predicate=str(fact.get('relation','')).strip().lower()
        affected=False
        if kind=='none':continue
        if fact['frame']=='unknown':affected=True
        elif kind=='frame_rotate':
            affected=fact['frame']==frame and (frame!='object' or not targets or owner in targets)
        elif kind in {'object_move','object_remove'}:
            affected=bool(names&targets) or predicate in {'occludes','occluded_by','visible','visibility'}
        elif kind=='object_rotate':
            # A proposed object rotation may include motion about a pivot.
            # Conservatively recheck endpoint-dependent relations; never infer
            # a new relation or assume an unchanged camera/world position.
            affected=(fact['frame']=='object' and owner in targets) or bool(names&targets)
        if affected:
            fact['post_validity']='must_recompute';changed.append(i)
    return result,{'status':'supported','changed_fact_indices':changed,'changed_count':len(changed),
                   'facts_count':len(facts),'verified_scene_facts':False}
