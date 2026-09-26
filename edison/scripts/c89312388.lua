--Elemental HERO Prisma - Edison override (April 2010 text, edisonformat.net/rules/errata)
--2010: "Once per turn: You can activate this effect; You can reveal 1 Fusion Monster from your Extra
--       Deck, and send 1 Monster from your Deck to the GY, whose name is specifically listed on that
--       Fusion Monster, and until the End Phase, the name of this card becomes the sent monster's."
--Site: "This effect has no cost. If Prisma is not on the field, none of the effect resolves."
--Change: the reveal + send move from the cost (REASON_COST, at activation) into the operation
--(REASON_EFFECT, at resolution, only if Prisma is still face-up on the field).
--E・HERO プリズマー
--Elemental HERO Prisma
local s,id=GetID()
function s.initial_effect(c)
	--cos
	local e1=Effect.CreateEffect(c)
	e1:SetDescription(aux.Stringid(id,0))
	e1:SetType(EFFECT_TYPE_IGNITION)
	e1:SetCountLimit(1)
	e1:SetRange(LOCATION_MZONE)
	e1:SetTarget(s.costg)
	e1:SetOperation(s.cosoperation)
	c:RegisterEffect(e1)
end
function s.filter2(c,fc)
	if not c:IsAbleToGrave() then return false end
	return c:IsCode(table.unpack(fc.material))
end
function s.filter1(c,tp)
	return c.material and c:IsType(TYPE_FUSION) and Duel.IsExistingMatchingCard(s.filter2,tp,LOCATION_DECK,0,1,nil,c)
end
function s.costg(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return Duel.IsExistingMatchingCard(s.filter1,tp,LOCATION_EXTRA,0,1,nil,tp) end
end
function s.cosoperation(e,tp,eg,ep,ev,re,r,rp)
	local c=e:GetHandler()
	if not c:IsRelateToEffect(e) or c:IsFacedown() then return end
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_CONFIRM)
	local g=Duel.SelectMatchingCard(tp,s.filter1,tp,LOCATION_EXTRA,0,1,1,nil,tp)
	if #g==0 then return end
	Duel.ConfirmCards(1-tp,g)
	Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TOGRAVE)
	local cg=Duel.SelectMatchingCard(tp,s.filter2,tp,LOCATION_DECK,0,1,1,nil,g:GetFirst())
	if #cg==0 or Duel.SendtoGrave(cg,REASON_EFFECT)==0 then return end
	local e1=Effect.CreateEffect(c)
	e1:SetType(EFFECT_TYPE_SINGLE)
	e1:SetCode(EFFECT_CHANGE_CODE)
	e1:SetProperty(EFFECT_FLAG_CANNOT_DISABLE)
	e1:SetReset(RESETS_STANDARD_PHASE_END)
	e1:SetValue(cg:GetFirst():GetCode())
	c:RegisterEffect(e1)
end