--Mausoleum of the Emperor - Edison override (April 2010 text, edisonformat.net/rules/errata)
--2010: "...during the resolution of this effect, they Normal Summon 1 monster from their hand, which
--       requires that many tributes, without Tributing."  Site: "Summoning happens during the
--       resolution, not 'immediately after this effect resolves'. Solemn Judgment cannot negate this Summon."
--The core always defers a Summon called during a chain until the chain ends (libduel Summon ->
--core.reserved), which is exactly the current "immediately after". No script can Summon strictly
--mid-resolution, so this reproduces the consequence the site names: the Summon cannot be negated
--(EFFECT_CANNOT_DISABLE_SUMMON makes the core skip the negation window). PARTIAL: other timing
--consequences of "during resolution" are not reproduced.
--死皇帝の陵墓
--Mausoleum of the Emperor
local s,id=GetID()
function s.initial_effect(c)
	--Activate
	local e1=Effect.CreateEffect(c)
	e1:SetType(EFFECT_TYPE_ACTIVATE)
	e1:SetCode(EVENT_FREE_CHAIN)
	c:RegisterEffect(e1)
	--Activate 1 of these effects
	local e2=Effect.CreateEffect(c)
	e2:SetDescription(aux.Stringid(id,0))
	e2:SetCategory(CATEGORY_SUMMON+CATEGORY_SET)
	e2:SetType(EFFECT_TYPE_IGNITION)
	e2:SetProperty(EFFECT_FLAG_BOTH_SIDE)
	e2:SetRange(LOCATION_FZONE)
	e2:SetTarget(s.sumefftg)
	e2:SetOperation(s.sumeffop)
	c:RegisterEffect(e2)
	--Hardcode
	local e3=Effect.CreateEffect(c)
	e3:SetType(EFFECT_TYPE_SINGLE)
	e3:SetCode(80921533)
	e3:SetValue(SUMMON_TYPE_NORMAL)
	c:RegisterEffect(e3)
	e2:SetLabelObject(e3)
end
function s.sumfilter(c,se,ct)
	if not (c:IsSummonableCard() and c:CanSummonOrSet(false,se)) then return false end
	local mi,ma=c:GetTributeRequirement()
	return mi==ct or ma==ct
end
function s.sumefftg(e,tp,eg,ep,ev,re,r,rp,chk)
	local se=e:GetLabelObject()
	local b1=Duel.CheckLPCost(tp,1000) and Duel.IsExistingMatchingCard(s.sumfilter,tp,LOCATION_HAND,0,1,nil,se,1)
	local b2=Duel.CheckLPCost(tp,2000) and Duel.IsExistingMatchingCard(s.sumfilter,tp,LOCATION_HAND,0,1,nil,se,2)
	if chk==0 then return Duel.GetLocationCount(tp,LOCATION_MZONE)>0 and (b1 or b2) end
	local op=Duel.SelectEffect(tp,
		{b1,aux.Stringid(id,1)},
		{b2,aux.Stringid(id,2)})
	Duel.PayLPCost(tp,op*1000)
	e:SetLabel(op)
	Duel.SetOperationInfo(0,CATEGORY_SUMMON,nil,1,tp,LOCATION_HAND)
end
function s.sumeffop(e,tp,eg,ep,ev,re,r,rp)
	local op=e:GetLabel()
	local se=e:GetLabelObject()
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_SUMMON)
	local sc=Duel.SelectMatchingCard(tp,s.sumfilter,tp,LOCATION_HAND,0,1,1,nil,se,op):GetFirst()
	if sc then
		local e1=Effect.CreateEffect(e:GetHandler())
		e1:SetType(EFFECT_TYPE_SINGLE)
		e1:SetCode(EFFECT_CANNOT_DISABLE_SUMMON)
		e1:SetProperty(EFFECT_FLAG_CANNOT_DISABLE+EFFECT_FLAG_UNCOPYABLE)
		e1:SetReset(RESET_EVENT|(RESETS_STANDARD&~RESET_TOFIELD)|RESET_PHASE|PHASE_END)
		sc:RegisterEffect(e1)
		Duel.SummonOrSet(tp,sc,false,se)
	end
end