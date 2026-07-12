# 9.3 비모수적 검정과 점근적 비교

> OCR engine: macOS Vision (`ko-KR,en-US`)
> Original PDF pages: 379-398

<!-- page 379 -->

비모수적 검정과 점근적 비교

모집단 분포에 대한 모형의 설정에서 정규분포 또는 로지스틱분포와 같이 확률밀도 함수의 특정한 형태를 가정하지 않는 경우의 검정에 대하여 생각해보자. 예 9.3.1 위치모수 모형에서 부호검정 <예 8.4.3>에서와 같이 모집단 분포가 연속형이고 확률밀도함수가 12-8),-8<6X480 의 꼴로서 0에 관하여 대칭, 즉 f(-2)=f(z) V2: -8 C 2<+∞이고 9

## 에 대응하는 누적분포함수 F가 순증가함수인 모형을 생각해보자. 이러한 모형

## 하에서 랜덤표본 X1; ··, X, 을 이용하여 가설

F(0):0=B. Us H:0280 을 유의수준 a(0 < a< 1)에서 검정할 때, 통계량 S,,=

## 2IX;280)

i= 1 을 이용하는 방법에 대하여 생각해보자.

## 이 경우에 통계량 S,의 분포에 대하여

5,~B(m.p(0)), p(0)=Po(X,>80)=1-F(8,-8) 임을 알고 있고, 위의 가설이 p(8)에 관한 가설 I(1/2):p(0)= 1/2 vs H:p(0)> 1/2 에 대응하므로 다음과 같은 검정을 유의수준 a의 검정으로 사용할 수 있다. (1, S,≥e+1 0,(X1,X,)=57, Sn= c 0≤7≤ 1) 0, S,sc-1 Bo.0.(X)=Po(5,2C+1)+YPa,(5,=c)=4 주 17(112)+72)(/2) =0 이 경우에 =c+1 Foo.(X1x,)=ED:(21+0,,2,+0), 2i~f(i= 1,…,7) 이고, 0, (21,2m)이 각 성분 2(i= 1,•7)의 증가함수이므로 다음이 성립 한다.

<!-- page 380 -->

maxboo. (X)=E8.0.(X)=a 8≤ 80 따라서 위의 검정 0,는 가설 Ho:0≤lo us 11:0200 에 대한 유의수준 a의 검정으로 사용할 수 있다. 이와 같이 통계량 S, 을 사용하 여 연속형 분포의 중앙값에 대한 검정을 하는 방법을 부호검정(1) 1T, Sign test)이라고 한다. 이러한 부호검정은 모집단 분포에 대하여 특정한 함수 형태를 가정하지 않고도 사 용할 수 있는 범용성(ALTH;, robustness)이 있는 반면에 특정한 모집단에 적용하면 효 율성이 떨어질 수도 있을 것이다. 이러한 효율성의 판단에는 주로 특정한 대립가설에 서의 검정력을 일정한 수준으로 유지하기 위하여 필요한 표본크기를 비교의 기준으로 사용한다. 예 9.3.2 위치모수 모형에서 부호검정의 검정력 근사 <예 9.3.1>의 가설 B(0):0=0o vs 1:0200

## 에 대한 부호검정 통계량 S,의 극한분포에 대하여 이항분포의 정규근사를 적

용하면 S,-mp(0) d vna2⑧) n-∞ -N(0,1), o2(0)=p(0)(1-p(0)) 이 성립하므로, 표본크기가 클 때 유의수준 a의 기각역을 다음과 같이 근사할 수 있다. "S,≥c,", Cn=mp(lo)+yno(Bo)za, p(Bo)=1/2, 0(0.)= 1/2 따라서 대립가설 0= 0, (0, > 0,)에서의 검정력은 다음과 같이 근사할 수 있다. 1n (8,)= Po,(5, 2 can) = Po, S,-mp(01) 2s-mp(8.)) (no2(0.) Vna2(0.)

## ~P.

Z≥ Cn- np(61))

## ,Z~ N(0,1)

=1-$(-Vn(p(0,)-p(00))/0(0,)+0(00)220(0.)} 394 9장 검정의 비교

<!-- page 381 -->

그러므로 고정된 대립가설 0= 0, (0, > 0.)에 대하여는 limm (01)= 1 이 성립하고, 귀무가설에 가까이 접근하는 대립가설 B1n=0,+k/vn (K>O) 에 대하여는 다음과 같은 근사식이 성립한다. 76(8)=1-817(01-8)p(0)0(0)+2, p()=807(0)=10,-0) 따라서 7,(@in)= 7이기 위해 필요한 표본크기는 근사적으로 다음과 같이 구 할 수 있다. vn(81,-80)800)0(80)-20=31-7 :n=(2(0)2 20+ 21 0in - 80 정리 9.3.1 검정력의 근사와 표본크기 실수인 모수 0에 관한 가설 H(8):0= 00 0S 1:020 을 유의수준 a(0< 0< 1)에서 검정할 때 크기 72인 랜덤표본에 기초한 검정 통계량 In을 이용한 크기 c인 기각역의 형태가 다음과 같다고 하자. vn(T,-n(0))/080)≥t2 또한 검정통계량 1m에 대하여 vi(1,-K(8)/0(0) LN(0.1) 과 같은 점근정규성이 성립하고(32) (0), o(0)는 각각 미분가능하고 연속인 함 수라고 하자. (a) (검정력의 근사) 귀무가설에 가까이 접근하는 대립가설하의 모수 01=0,+&/V(K>0) 에 대하여 다음과 같은 검정력의 근사식이 성립한다.

132) 엄밀하게는 6u=0,+&/ vn(&> 0)에서의 점근정규성을 필요로 하고, 이는 8. 근방

의 열린 구간에서의 0들에 대한 균등점근정규성(1)쪽 Pri IE※EM, uniform asymptotic normality)이 성립되면 충분하다.

<!-- page 382 -->

7,(8m)=Pon(vn(t,-w(80)10(8,)2t,) 21-9-(01-0)i:(0)(00)+3a, i)= 1(0) (b) (표본크기의 근사) (a)에서의 대립가설하의 모수 8, 에서의 검정력이 7, 즉 Ta (8n) = 7 이기 위해 필요한 표본크기를 (Th;7, 0,,)이라고 하면 다음의 근사식이 성립한다. V(Tm;7, 5in [증명] 점근정규성이 성립하고, 검정의 크기가 a이므로 Po.tvn(1,-1(8)/0(8,)≥t,}=0,P(22t,)=0,2~N(0,1) .. tn=&a 따라서 대립가설 0=0,(0, > 0g)에서의 검정력에 대하여 다음 근사식이 성 립한다. 7(0.)=Po(vn(Tn-k(8,)10(6)≥50)

## -P:/75,180) 2(8)

a(0,) a(0.) +cm스(8,)-M(0.) 0(0.) -Pa(22-274(0)-1(00) a(0.) a(0,)

## Z~N(0,1)

=1-호-vn((8,)-w(00))/o(0,)+200(0,)10(0.)} 그러므로 0,,=0,+A/Vn(K> O)에서의 검정력을 다음과 같이 근사할 수 있다. 7,(8)=1-91-Vn(6.-00)i(0,)o()+za1 또한 표본크기 (Tn; 7, 01,)의 근사식은 다음의 근사계산으로부터 얻을 수 있다. VN(1;7;8.)(81n-80)(8,)/0(8.)-20=31-7 점근상대효율성: 실수인 모수 0에 관한 가설 1(0):0=8. 26 1:028 396 9장 검정의 비교

<!-- page 383 -->

을 유의수준 0(0< a< 1)에서 검정할 때 크기 인 랜덤표본에 기초한 검정통계량 Tm (i=1,2)들이 정리 9.3.1>의 조건들을 만족시킨다고 하자. 또한 대립가설하의 모수 0un=0,+A/Vn(K>O)에서 검정력이 7이기 위해 필요한 표본크기를 N(Tmi7,0in) (i=1,2)이라고 할 때, 이들 표본크기의 역수의 극한 값 limN-'(Thin;6)/N-(127,6) 을 Zin에 의한 검정 방법 1의 2,에 의한 검정 방법 2에 대한 점근상대효율성(#F: 차담보 주사보, asymptotic relative efficiency)이라고 한다. 이러한 점근상대효율성을 기 호로는 ARE({Zin),(72a)로 나타내고, 이는 〈정리 9.3.1)로부터 다음과 같이 나타 내어진다. ARE({Tm)(Ta)=lim-(Tnin,0m)/N (Tznin lm) =(i(0)10,(80)26is(8)102100)2 예 9.3.3 부호검정의 t 검정에 대한 점근상대효율성 모집단 분포가 연속형으로서 µ에 관해 대칭이며 확률밀도함수가 -8CB<+8, 0>0 인 경우에도, 가설 Ho(0): K= 10 0s H:A> A0 을 유의수준 a(0< a< 1)에서 검정하려면 통계량 S,= LIX;> 1) 을 이용하는 부호검정을 <예 9.3.1>에서와 같이 적용할 수 있다. 이 경우에도 Min= 1o+K/ Vm(K> 0)에서 부호검정에 의한 검정력이 7이기 위해 필요한 표본크기는 <예 9.3.2>에서와 같이 N(5,in.Min)=(28(0)/0)-22at21-2)3 kin - A0 으로 주어진다. 한편 모집단의 분포가 정규분포라면 "Vn(X-M)/S≥ta(n-1)” 로 주어지는 t 검정을 사용할 것이다. 이러한 t 검정의 통계량 Tn=vn(X-80)S

<!-- page 384 -->

에 대하여 다음과 같은 점근정규성이 성립하는 것을 알 수 있다. 133) ✓” X-A0 An-Ao vVar(Xj) 따라서 t 검정의 경우에 표본크기의 근사식은 <정리 9.3.1>로부터 다음과 같이 주어진다. NT:nAm)=(1/yvarxj)-230t21-2 Kin- 1o 그러므로 부호검정의 t 검정에 대한 점근상대효율성은 ARE(5),(Za})=(21(0)/o):/(1/VVar(X.)=4((0)/ 22f(a)dz 으로 주어지고, <예 8.4.3>으로부터 이는 추정량으로서 표본중앙값의 표본평균에 대한 점근상대효율성과 같은 것을 알 수 있다. 표 9.3.1 부호검정의 t 검정에 대한 점근상대효율성 모집단 분포 N(p,o2) L(4,q) DE(p,a)

## ARE((S. (1,})

2/= 0.636.. 2/12= 0.822... 부호검정과 같이 모집단 분포에 대하여 특정한 함수 형태를 가정하지 않고도 사용 할 수 있는 검정 방법을 비모수적(:} wkis, nonparametric) 검정이라고 하며, 이러한 방법은 모집단 분포에 대한 가정의 타당성을 판단하기 어려운 경우에 유용한 방법이 다. 이러한 비모수적 검정의 가장 대표적 방법인 크기 순서를 이용하는 방법에 대하여 알아보자. 예 9.3.4 위치모수 모형에서 부호순위 검정통계량 <예 9.3.1>에서와 같이 모집단 분포가 연속형이고 확률밀도함수가 f(2-8), -8<0<+8 의 꼴로서 0에 관하여 대칭, 즉 f(-2)=f(2) V2: -∞< 2<+∞인 경우

## 에 랜덤표본 X 1, ··, X,,을 이용하여 가설

1,(00):0=0, 0s H: 0≥00

133) 모평균이 1u,= Mo+A/vn(K> 0)일 때의 극한분포를 뜻하는 것이다.

398 9장 검정의 비교

<!-- page 385 -->

을 검정한다고 하자. 이 때 IX, 80, , IX, 0d을 작은 것부터 크기 순서로

## 나열하는 경우에 IX,- 8d의 크기 순서를 IX,-8,의 순위라고 하며 R(X,-8g)

로 나타내고, 즉 R(X:-00)= 1+ 2I(X,-80< IX,-801) 이고 다음의 통계량을 부호순위(PrEE At, signed rank) 검정통계량이라고 한다. \;,= sgn(X-0,)R(X,-0g) 여기에서 5gn (2)는 2의 부호를 나타내는 함수이다. 정리 9.3.2 부호순위 검정통계량의 귀무가설하의 분포 귀무가설 1(0g) : 0= 0, 하에서 부호순위 검정통계량의 분포에 대하여 다음이 성립한다. (a) W,,= Lis(j), S(j):tid, P(S(j)= -1)=P(S(j)= +1)= 1/2 (j= 1,…·,n) (b) (H,-Bo.4,) wVaro,(1,) 72-*00

## - N(0,1).

Bo,(Wa)=0, Varo,(W,)= j=1 Li2=n(n+1)(2n+1)/6 [증명] 증명 과정에서 부호 벡터와 순위 벡터를 각각 다음과 같이 나타내기로 한다. S=(S(1),…S(n)'=(sgn(X,-0,),,sgn(X, -8,)), R=(R(1),,R(2)'= (R(X」-00),,R(X,-8.))' (a) 첫째로 귀무가설 1o(0g) : 0=0, 하에서 X의 분포가 0,에 관하여 대칭이 므로 Po.(X,-80 st,sgn(31-80)= +1) = Po.(0<X,-8,≤2) 2P0(X,-801≤2) =Po.(X,-00Sz)P0,(sgp(&1-80)= +1); Po.1X1-00St,sgn(X1-80)=-1)

<!-- page 386 -->

=Po.(X1-805a)Pg, (8gp(X1-80)= -1) 즉 귀무가설 1(0g): 0= 0,하에서 IX,-8.와 Sgn(X, -8.)가 서로 독립 이고, 부호 벡터 S=(S(1),·,S(n)'와 순위 벡터 R=(R(1),··,R(7))'는 서로 독립이다. 둘째로 R(i)=J일 때 i=R-'(j)로 나타내는 역순위 벡터를 R-'= (R-'(1),,R-'(n))'라고 하면 부호순위 검정통계량을 다음과 같이 나타낼 수 있다.

## 한편 X,,

•··, X, 이 서로 독립이고 동일한 분포를 따르므로, {1,2,·p}의 임의의 치환 에 대하여 다음이 성립함을 알 수 있다. (Saj) sjsn=(gp(X76)-8)sjsn=(sgp(X,-80)sjsm =(Sj)1sjsn 또한 귀무가 Ho (0) : 0= 0, 하에서, S=(S(1),••,S(n)'와 R=(F(1), •••,R(n))'의 독립성으로부터 다음이 성립함을 알 수 있다. Po.(S(R-'(1)= 311S(R-'(7)= 3,) =2Po(SR (1))=31,S(R-'(0)=SnR=T) =2P0(ST(1)= 51•S(1(7)= Sm,R=T) =2P 0(5('(1)= 31,9(-(7)= 8,)Po,(R=T) =P0(1)= 38(m)= 3)P0,(R=T) = Pe,(5(1)= 51°,5(r)= 3m) 따라서 귀무가설 Fo(o) : 0 = 0,하에서 다음이 성립함을 알 수 있다. j=1 ;sR-6),= 23s6) 또한 귀무가설 Ho (0): 0= 8, 하에서 X, 의 분포가 0,에 관하여 대칭이므로 Pe.(S(j)= - 1)= Po,(S(1) = +1)= 1/2 400 9장 검정의 비교

<!-- page 387 -->

이고, (a)가 성립하는 것을 알 수 있다. (6) 0,= VVarg,(Wa), Z,= 1,/o,이라고 하면, (a)로부터 Bo(t,)=0, 0h=Varo(W,)= 273=n(n+1)(200+1)/6 또한 (a)로부터 귀무가설 1(0g) : 0= 0,하에서 Z,의 누율생성함수를 다음 과 같이 근사할 수 있다. 912(0)=25108((exp(-30/on)+explto.)/2} = ½h hR+ ... ~ 12g2 그늘아+ .. 따라서 귀무가설 1(0g) : 0= 0, 하에서 I, 의 점근정규성이 성립한다. 즉 (H,-Bo.Wm)/wVaro(W,)= 2,12

## • N(0,1)

정리 9.3.3 부호순위 검정통계량의 표현

## W1-E00,-0,20)2(X,-0.)

라고 하면 다음이 성립한다. (a) I,=2W,*-n(n+1)/2 (b) 귀무가설 H, (0,) : 0= 0,하에서 (7,t-n(n+1)/4)/~n(n+1)(2n+1)/24 d 72-*8

## * N (0,1)

[증명] 모집단 분포가 연속형이므로 sgn(X:-0,)=21(X:-0,>0)- 1

<!-- page 388 -->

이고, 이를 IV,= 27sgn(X,-9.)R(X,-0)에 대입하여 정리하면 (a)가 성립하는 것을 알 수 있다. 또한 <정리 9.3.2>의 (a)로부터 W%=(7+n(2+1)/2)/2=2:(56)+1)12 이므로 (b)가 성립하는 것을 알 수 있다. <정리 9.3.2~로부터 귀무가설 1g (0) : 0= 0, 하에서 부호순위 검정통계량 I, 의 분포는 모집단 분포의 확률밀도함수 형태에 관계없는 분포를 갖는 것을 알 수 있으며 I, 의 큰 값은 대립가설 1, : 0> 0,에 대한 증거라고 할 수 있다. 따라서 56(0):0=8. us 1:0280 에 대한 유의수준 a의 부호순위 검정은 다음과 같이 주어진다. 1, M,,≥c+1

## DsR(X 1,X

.,.) 0, W,sC-1 7, Wn=e (0sys1), Eopsnlx)=a 또한 <정리 9.3.3>으로부터 I,*를 이용하여 이를 다음과 같이 나타낼 수도 있다. 1, W,+≥¢++1

## OsR(XI,

## •,X

1.)= 7, W=e (0≤7≤1), Bopsn(X)=a 0, W,+≤ct-1 이러한 과정에서 필요한 1, 또는 WW,t의 귀무가설하의 누적확률은 부록 II에 소개

## 되어 있는 패키지 R을 이용하여 계산할 수 있다.

한편 <정리 9.3.2>와 <정리 9.3.3>으로부터 표본크기가 클 때 유의수준 a의 기각 역은 다음과 같이 근사할 수 있는 것을 알 수 있다. "W,/vn(n+1)(2n+1)/6≥ 20” 또는 "(W,-n(n+1)/4)/vn(n+1)(2n+1)/24≥ 20" 정리 9.3.4 한쪽 가설에 대한 부호순위 검정 모집단 분포가 연속형이고 확률밀도함수가 12-0),-8<0<48 의 꼴로서 0에 관하여 대칭, 즉 f(-2)=f(z) Vz: -∞<aC+∞인 경우

## 에 랜덤표본 X 1, , X,,을 이용하여 가설

402 9장 검정의 비교

<!-- page 389 -->

10:0≤00 0s 11:0≥ 80 을 유의수준 a(0 < a< 1)에서 검정할 때, 부호순위 검정 Osn에 대하여 다음이 성립한다. (a) W,= 2 lSisjsn 2 IX,+X;> 200) (6) 검정력 함수 710g(8) = Eose(X)는 8의 증가함수이고, 다음이 성립한다. maxBoosn(X)= Boosa(x)=a [증명] (a) Y, = X,-9를 사용하여 W%를 다음과 같이 나타낼 수 있다.

## 2(20)+2210,20,-Y,CY,CY)

=5:1020)+22(020,-r0cYC) 718,20)+22:(1,+8,20) =2. 2(0.+1,20) (b) 부호순위 검정의 정의 (1, W,t≥¢++1 Osn(X1,…,X)=7, Wat=ct (0≤7≤1) (0, W,t≤ ct-1 로부터 Osn(X 1,·•,X)은 W%*의 증가함수이다. 그런데 (a)로부터 이므로 W,*는 각각의 X(i=1,…,m)의 증가함수이다. 따라서 Ose(X 1, •·,X,,)은 각 성분 X (i= 1,…,n)의 증가함수이다. 한편 이 검정의 검정력

<!-- page 390 -->

함수를 70m(0)=Eoosa(X1,,%,)= EOsn(Z1+6,,Z,+0), Zi~fli=1,,m) 과 같이 나타낼 수 있으므로 검정력 함수 10g(8)는 8의 증가함수이고 (6) 가 성립한다. <정리 9.3.4>로부터 알 수 있듯이, 연속형의 대칭인 분포의 중앙값에 대한 한쪽 가 설이나 양쪽 가설의 검정에 부호순위 검정을 사용할 수 있고, 이는 모집단 분포의 특 정한 형태를 가정하지 않고도 사용할 수 있는 비모수적 검정이다. 이러한 부호순위 검 정의 효율성을 알아보려면 다음과 같은 점근정규성이 필요하다. 이 정리의 증명은 이 책의 수준을 넘으므로 생략한다. 정리 9.3.5 부호순위 검정의 점근정규성

## 부호순위 검정에서의 검정통계량 W,+에 대하여 다음의 근사식이 성립한다.

(a) W,+-Eo(W,t) d VVarg(W,t) 2-00 -> (0,1) (6) A(6)= dPo(X,+X2> 200) o2(0) = Cov(I(X, +X2> 20,2 I(X, +X3 > 20,)라고 하면 Eo(W,t)=n2p(0), Vare(W,t)=n382(0) <정리 9.3.5>로부터 통계량 2+/n'에 정리 9.3.1>을 적용할 수 있으므로 부호순 위 검정의 검정력에 대한 근사식을 다음과 같이 구할 수 있다. 정리 9.3.6 부호순위 검정의 검정력 근사와 표본크기 <정리 9.3.4>의 가정하에서 부호순위 검정에 대하여 다음의 근사식이 성립한다. (a) (검정력의 근사) 대립가설하의 모수 81,= 0,+ K/vn (&> 0)에 대하여 10m(0)=1-51Vm(01-0,)i(8)/0(0,)+za}. i(Bo)=/ •+ 801 f:(z)dz, o2(0.) = 1/12 404 9장 검정의 비교

<!-- page 391 -->

(b) (표본크기의 근사) 7, (0km)= 이기 위해 필요한 표본크기 (W,;7,0km ) 에 대하여 P(t)ar) 6in - 60 [증명] <정리 9.3.5에서 p(0)와 o2(0.)를 구해보면 1(0)=늘/.. (1-F(20,- 20-2))f(2)dz, 02(0)=El(1-F(-2)']-[E(1-F(-2))], 2~F =E(U2)-[E(U)), U~U(0,1) 이므로 <정리 9.3.1>로부터 (a), (b)가 성립하는 것을 알 수 있다. 예 9.3.5 부호순위 검정의 t 검정에 대한 점근상대효율성 모집단 분포가 연속형으로서 에 관해 대칭이며 확률밀도함수가 인 경우에도, 가설 H(w):M= No vs H:A> M 을 유의수준 2(0< a< 1)에서 검정하려면 통계량 1,=Lsgp(X,-00)R(X,-80) 을 이용하는 부호순위 검정을 <정리 9.3.4>에서와 같이 적용할 수 있다. 이 경우에도 Kin = Ko+ K/vn (K> 0)에서 부호검정에 의한 검정력이 7이기 위해 필요한 표본크기는 <정리 9.3.6>에서와 같이 N(WiniAn)=Vis/o 'Plaslo] 1in- 10 으로 주어진다. 한편 <예 9.3.3>으로부터 t 검정의 경우에 필요한 표본크기는 N(T,;7:Min)=(1/VVar(X)) 2a+ 2-1 1in- 10

<!-- page 392 -->

- ∞

그러므로 부호순위 검정의 t 검정에 대한 점근상대효율성은 APE(7):(2)= 12//50 (Plabda) / 22f(z)dz 으로 주어지고, 모집단 분포에 따른 점근상대효율성의 값은 <표 9.3.2>에서와 같 다. 이 표와 부호검정에 대한 <표 9.3.1>을 비교하여 보면 부호순위 검정의 상대 효율성이 부호검정에 비하여 매우 높은 것을 알 수 있다. 심지어는 정규분포의 경우에도 그 점근상대효율성이 95%에 이르는 것을 알 수 있다. 즉, 부호순위 검 정은 모집단 분포의 특정한 형태에 대한 가정이 없이도 사용할 수 있다는 범용성 과 더불어 효율성도 비교적 높아서 매우 유용한 검정 방법이다. 표 9.3.2 부호순위 검정의 t 검정에 대한 점근상대효율성 모집단 분포

## N(4,02)

[((,a) DE(4,q)

## ARE({W,),{T.l)

3/ㅠ= 0.954... 2/9= 1.096... 1.5 406 9장 검정의 비교

<!-- page 393 -->

큰편한유포영 다변량 정규분포 신뢰 십입 지환 계수 회귀계수 고유값 선형회귀모형 정칙행렬 정칙 다변량 정규분포 확듈석문변환 중심극한정리 표본회귀계수 단순 설명변수 점근 대수의 법칙 표본적률 극한분포 점근분포 평균오차? 난수 첨예도 균등난수 표본상관계수 분위수 분산안정변환 표본분위수 「능도 추정법 추정 추정량 일치성 몬테칼로적분 가능도 할수 적률이용추정량 다중모수 지수족 점수함수 연습문제 가능도방정식 쿨백-라이블러 괴리도 순오목함수 간 확률측도 정사영 최소제곱 추정법 확률 최소제곱 추정량 점근정규성 랜덤한 실험 조건부확률 표본공간 포함수 확률밀도함수 확률변수 사전 가산가법성 이산형 사후 독립 펵규 기댓값 연속형 표주편차 이상 확률분포 확률질량함수 표주화 9.1 베르누이분포 Bernoulli(p), 0≤pS 1에서의 랜덤표본 X=(X1,•,X,,)' (n= 8)을 이용하여 다음 가설을 검정하려고 한다. Ho:p=1/2 vs 17,: D=3/4 (a) 다음의 베이지안평균오류확률을 최소로 하는 베이즈검정 p™를 구하여라. TOEo(X)+ㅉ,Bnl-o(X)] (To+찌=1,T>0,7>0)(po=1/2,P1= 3/4) (b) 위의 가설을 유의수준 a= 0.05에서 검정하려고 할 때 최강력 검정을 구 하여라. (c) (6)의 검정의 p= 3/4에서의 검정력 7(3/4)를 구하여라.

## 9.2 분산행렬 2가 알려진 정칙행렬인 다변량 정규분포 N, (W, 5)에서의 랜덤표

## 본 X1; , X, 을 이용하여 다음 가설을 검정하려고 한다.

Ho:K= Mo Us In: M=AI (o, Ar는 주어진 벡터이고 Mo 141) (a) 다음의 베이지안평균오류확률을 최소로 하는 베이즈검정 o"를 구하여라. TEnO(X)+지,E,1-0(X), (To+T,=1,7020,7120) (b) 위의 가설을 유의수준 a= 0.05에서 검정하려고 할 때 최강력 검정을 구 하여라. 9.3 정규분포 N(0,0), 0> 0에서의 랜덤표본을 X1; ·•·, X, 을 이용하여 가설 1o:0350 us 1, : 02> 03 (0은 주어진 양수) 을 검정할 때 유의수준 a(0< a< 1)의 전역최강력 검정을 구하여라.

<!-- page 394 -->

## 9.4 확률밀도함수가

J(t:0)=020-110.1)(z) 로 주어지는 베타분포 Beta(0,1), 0≥ 0에서의 랜덤표본 X1, ,X,을 이 용하여 가설 H: 0≤00 vs 1 : 0>8, (0,는 주어진 양수) 을 검정할 때 유의수준 a(0< a< 1)의 전역최강력 검정을 구하여라.

## 9.5 확률밀도함수가

J(3;0)=020-111,0)(2) 로 주어지는 파레토분포 Pareto(1,0), 0> 0에서의 랜덤표본 X1, ••, X,,을 이용하여 가설 10:0≥0 vs 1,:0<0. 0,는 주어진 양수) 을 검정할 때 유의수준 a(0< a< 1)의 전역최강력 검정을 구하여라. 9.6 지수분포 Exp(0), 0<0<+∞에서의 랜덤표본 X1,··,X,을 이용하여 H: 0=0, VS H, : 0ㅊ 0, (6,는 주어진 양수) 을 검정할 때 유의수준 a(0< a< 1)의 전역최강력 검정이 존재하지 않음을 밝혀라.

## 9.7 확률밀도함수가

J(e;0)=02°-lexp(-20)10.+∞)(z) 인 와이분포 Weibull(8,1)에서의 랜덤표본을 X1; ···, X,을 이용하여 가설 H0:0=1 vs H:0≥ 1 을 검정할 때 유의수준 a(0< a< 1)의 전역최강력 검정이 존재하지 않음을 밝혀라. 9.8 지수분포 Exp(0), 0<0<+∞에서의 랜덤표본 X=(X1, ,X,)'을 이용하 여 가설 H0 : 0=0, Us 1, : 0ㅊ0, (8,는 주어진 양수) 408 9장 검정의 비교

<!-- page 395 -->

을 유의수준 a(0< a< 1)에서 검정할 때 두 조건 Bo.o(x) = a, = 0 을 만족시키는 검정 중에서 전역최강력 검정을 구하여라. 9.9 초기하분포 H(n;N,D), 1≤ DS N (m, N은 알려진 자연수)를 따르는 관련

## 측 자료 X를 이용한 다음의 가설 검정에 대하여 답하여라.

(a) Ho : D= Do vs H, : D= D, (Do: D은 주어진 자연수이고 Do< D1) 을 유의수준 0(0< a< 1)에서 검정할 때, 최강력 검정이 다음과 같이 주어 지는 것을 밝혀라. 0"(2)= 2: 2=C.(0S2S1), Epo(X)=a 1, 2≥c41 0, 2≤ c-1 (b) (a)의 검정이 다음 가설에 대하여 유의수준 a(0<a< 1)의 전역최강력 검정임을 밝히고, N= 60, 7=5, Do= 6, a= 0.01일 때 c와 7를 구하여 라.(<예 3.1.1> 참조) H:Ds Do us I: DXDO 9.10 균등분포 U0,01, 0> 0에서의 랜덤표본을 X= (X 1,…,X, )'이라고 할 때 다음에 답하여라. (a) 1: 0=0, Us 17,(0,) : 0= 0, (00:0,는 주어진 양수이고 0,> 0.) 을 유의수준 (0< Q< 1)에서 검정할 때, 다음 조건을 만족시키는 검정이 최강력 검정임을 밝혀라. 6°(2)= 1, 2(0) > 80; Bo.o(X)=0 (6) 1o: 0=0, 0s 117, : 0>0, (0,는 주어진 양수) 을 유의수준 a(0<a< 1)에서 검정할 때, 최대가능도비 검정이 전역최강력 검정임을 밝혀라.

<!-- page 396 -->

(C) 1: 0=00 vS 1, : 0ㅊ8, (0,는 주어진 양수) 을 유의수준 a(0< 0< 1)에서 검정할 때, 다음 검정 0"(X)가 전역최강력 검정임을 밝혀라. o°(z)= (1, 2(%) <oVa 또는 2(m)>80 0, 8vas mm)≤80

## 9.11 1리터당 주행거리가 15km라고 연비가 표시되어 있는 특정 자동차의 실제

연비를 조사하여 이보다 연비가 나쁜 증거가 뚜렷하면 더욱 정밀한 검사를 하려고 한다. 이를 위해 10대의 자동차를 랜덤추출하여 1리터당 주행거리를 측정한 결과 다음의 자료를 얻었다.

## 12.5 14.4 10.8 16.1 14.8 15.1

## 13.8 15.5 13.5 14.0

이 자동차의 실제 1리터당 주행거리를 0 km라고 하여, 검정하고자 하는 적 절한 가설을 세우고 유의수준 a= 0.05에서 부호검정을 하여라. 9.12 <예 9.3.3~에서와 같이 점근상대효율성을 알아볼 때, 정규분포에서 벗어나 는 모형으로서 확률밀도함수가 J(z)=(1-e)0(a)+c1 이 0<6<1,00>0), 0(2)= 로 주어지는 오염된(contaminated) 정규분포의 모형 음(프쓰. -∞<NK+ ∞, 0≥ 0를 상정하여 점근상대효율성의 변화를 조사하기도 한다. 이와 같이 오염된 분포의 모형에서 부호검정의 t 검정에 대한 점근상

## 대효율성 ARD(4S,},(Zh))의 공식을 구하고, 다음 경우에 그 값을 구하여

라. O.= 4, E= 0.01, 0.05, 0.10, 0.20,0.25

## 9.13 건강한 사람들의 심장지수(cardiac index)는 평균 3.50(iters/minm3)임이 알려

져 있다. 심장질환의 경험이 있는 사람들의 심장지수가 이보다 떨어지는지를 알아보기 위하여 20명의 심장질환 경험자에 대하여 조사한 결과 다음의 자 료를 얻었다. 410 9장 검정의 비교

<!-- page 397 -->

## 2.45 3.55 4.05 0.95 1.90 3.48 3.80 1.40

## 3.65 3.30

## 2.33 2.91 3.69 1.83 1.35 4.10 2.77 2.60 3.32 2.34

심장질환 경험자의 실제 심장지수를 0(liters/minm)라고 하여, 검정하고자 하는 적절한 가설을 세우고 유의수준 a= 0.05에서 부호순위 검정을 하여라. 9.14 연습문제 (9.13)에서 유의수준 a= 0.05의 부호검정을 하여라.

## 9.15 연습문제 (9.12)에서와 같이 오염된 정규분포의 모형을 상정하는 경우에 부

## 호순위 검정의 t 검정에 대한 점근상대효율성 ARE({W,), {T,})의 공식을

구하고, 다음 경우에 그 값을 구하여라. 0=4, E= 0.01,0.05, 0.10, 0.20, 0.25

<!-- page 398 -->

nent) 확률변수(8st random variable) 이산형(18w discrete type) 확률질량수(68주로 probability mass fuction) 확률밀도함수(1: 전 inction) 평균(푸ta mean) 기댓값(A값 expected value) 표준편차(184부금※ standard deviation) 표준화(1류#f standardized) 누적분포함수 pability density function) 연속형 ( continuous type) 이상(꽃; improper) 확률분포(63th probability distribution) 지표함수() 1) 또ml probability generating function) 적률생성함수(#푸소g moment generating function) 적률(87 moment) 누율생성하 e cumulative distribution function) 표준지수분포(3) standard exponental distribution) 멱급수(9)% powver series) 확률생 6제 cumulant generating function) 누율(⅝w cumulant) 이변량(bivariate) 확률벡터(random vector) 반복적분 (iterated integre) 생성함수(joint moment generating function) sint) 주변 (Bi marginal) 공분산(#+covariance) 상관계수(제 8%9) correlation coefficient) 결합적률 (습후 joint mor 조건부(1fwt conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산 결합누울생성함수(joint cumulant generating function) 합누율 (joint o ector) 전치(transpose) 평균벡터(mean vector) 분산공분산행렬(variance covariance matrix) 정부호 variance) 회귀함수(Bwik regression function) 평균제곱예측오차(mean squared prediction error) 행벡F) Ive definite) 기울기벡터(gradient vector) 헤시안행렬 단분포(꿈#3AT population distribution) 비복원추출(sampling without replace (Hessian matrix) 모집단(금빛 popul 랜덤추출(₩※랜덤htti simple random sampling) 랜덤표본(random sampl Ii population proportion) 초기하분포(함※1ht hypergeome ition) 복원추출(19 itth sampling i binomial distribution) 대의적 정의(ft 8.t) 도 repr with replacement) 이항분 al definition 다항분포(STAh multinomial dl E(wfola m geometric distribution, 다항계수(31%w multinomial coefficte on) 음이항전개식(negative mEAT negative binomia xpansion) 포아송(Poiss) 과정(Poisson process) y) 독립증분성 (indepe urrence rate) 정상성 ement) 비례성 (propo 희귀성(rareness) 지수분 ntal distribution) 감마분 분산분석과 : parameter) 척도모수(REE 평 distribution) 형상모수(JHR ormal distribution) 분위수(upper quanti meter) 표준정규분포(*※ TER 77 S 회귀분석 비율(Htt sample proportion) 표본평균(1A7E1 (봉꾸: parameter space) 통계량(iCBt 1 sta ratistics) 표본중앙값(ATA값 sample medi an) 표본분포(A57) san) 표본분산(품초슈) sample variance) 순서통계량 (107:Wa distribution) 위치모수(11m ftg location parameter) 척도모수(FE 8빛 scale 포(트AAth triangular distribution) 야코비안(Jacobian) 자유도(Ets degrees of freedor.

## 1) 이중지수(doubile exponential) 코쉬(Cauchy) 균등분포(벼¥ATh uniform distribur

분류모형(-TAm one way classification model) 신뢰집합 포(chisquared distribution) 신뢰수준 (1룸가 후 confidence level) 신뢰구간 (1등Ea confidence 1분변환(1835) probability integral transformation) 다변량 정규분포(8%로 THAt multivariate nor. #슴 confidence set) 치환(11R peri n) 정칙행렬(nons ingular matrix) 정칙 다변량 정규분포(TEE) 3평불 태값 characteristic value) 선형회귀모형(3209919m linear regression model) 설명변수(explanatory variable) 반응변수.. TElAt nonsingular multivariate normal distr •합(T※#제급한 mean squared error sum of squares) 중심극한정리(SL (8112 central limit theorem) 극한분포(68f limitins ble) 계수(1 rank) 회귀계수(미)를6% regression coefficient) 표본회귀계수(sample regression coefficient) 단순(Tw simple) d on) 점근분포(wriA T asymptotic distribution) 대수의 법칙(치※의 : law of large numbers) 표본적률(sample moment) 분위수(A) (1) n coefficient) 분산안정변환(유)※꽃은% 표본분위수(14f) (tW sample quantile) 슬럿츠키(Slutsky) 점근(wir asymptotic) 첨예도(*출& Kurtosis) 표본상관계수(특A9 6 sample 몬테칼로적분(Monte Carlo integration) 적률이용추정량(#존치FHrm method of moments estimator(MME)) 추정(HT estimation) 추정량(HE) Variance syabilizing transtormation) 난수(Rue random number) 균등난수(19¥월.k uniform randon (or) 일치성 (- ) 가능도방정식(nathert likekihood equation) 순오목함수(strictly concave function) 경계(185f boundary) 다중모수 지수족(3로 1분 1텁보 1k multi

- 1h consistency) 가능도 함수(a bErs)

2w ikelihood function) 우도(XIE) 최대가능도 추정법(XONE) 1th maximum likelihood e exponential family of pdf s) 쿨백-라이블러 괴리도(Kullback-Leibler divergence) 점근정규성 (#iT IE refr asymptotic normality) 점수함수(score functio dicular projection) 공리(Ai axiom) 표본공간(121 sample space) 확률(mw probability) 가산가법성(countable additivity) 확률측도 (서울 2e Tit proba 육료 information number) 최소제곱 추정법(least squares estimation) 최소제곱 추정량(least squares estimator) 열벡터 공간(column space) 정사영(TE) ure) 조건부확률(151 fie conditional probability) 사전(whi prior) 사후(wts posterior) 독립 (3t mutually independent) 종속(611 mutually depende 실험(random experiment) 확률변수(187%8 randon variable) 이산형 (월 discrete type) 확률질량함수(제주 mEg probability mass fuction) 률밀도 nction) 평균(푸k mean) 기댓값(배A값 expected value) 표준편차(1¾916※ standard deviation) 표준화(111l standardized) 누적분포함수(및 p #g probability density function) 연속형(+ continuous type) 이상(토W improper) 확률분포 (139 7h probability distribution) 지표함수(1급제 ( 9) stribution function) 표준지수분포(4):h) fj standard exponential distribution) 멱급수(Www power series) 확률생성함수(1*±EW probability g ) 이변량(bivariate) 확률벡터(random vector) ction) 적률생성함수(Nientage moment generating function) 적률(통 moment) 누율생성함수(빛부tEl cumulant generating function) 누율(% n coefficient) 결합적률(제주 joint moment) 결합적률생성함수(joint moment generating function) 결합누율생성함수(joint cumulant generating ur 반복적분(iterated integral) 결합( joint) 주변 (Bmarginal) 공분산(AA) covariance) 상관계수(차) 굴(joint cumulant) 조건부(1%4fi conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산(conditional variang agEl regression function) 평균제곱예측오차(mean squared prediction error) 행벡터 column vector) 전치(transpose) 평균벡터 (mean vector) 분산: variance covariance matrix) 정부호(nonnegative definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(19 population) 모집단 비율(Bit% population proportion) 초기하분포()fltm hypergeometric distribution) 복원추출(19ithtt sampling with replacement) 이항분포 ht population distribution) 비복원추출(sampling without replacement) 단순랜덤추출(1※랜덤HtH simple random sampling) 랜덤표본(random tent) 기하분포(#mA hi geometric distribution) 음이항분포(9) homial distribution) 대의적 정의(fLad9 Ti representational definition 다항분포(3pAth multinomial distribution) 다항계수(3 1E 66 gt multino (Poisson) 포아송 과정(Poisson process) 발생률(occurrence rate) 정상성(stationarity) 독립증분성(independent increment) 비례성 (proportiona TA m negative binomial distribution) 음이항전개식(negative binomial expan 정규분포(1¾24 TER standard normal distribution) 분위수(upper quantile) 모수공간(2ml parameter space) 통계량(유미 statistir eness) 지수분포(exponential distribution) 감마분포(gamma distribution) 형상모수(TNt w shape parameter) 척도모수(RI f gy scale pa *tt sample proportion) 표본평균(7451) sample mean) 표본분산(유: sample variance) 순서통계량(IF) A:4값 sample medi an) 표본분포(24th sampling distribution) 위치모수(#물fg location parameter) 척도모수(F8 : h order statistin 2r) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(1)종ATi uniform distribution) 삼각분포(=Afth triangular distributio cobian) 자유도(Bill degrees of freedom) confidence interval) 일원분류모형 카이제곱분포(chi-squared distribution) 신뢰수준 1금가 t confidence level) 신뢰: on) 확률적분변환(HT HAWl probability integral transformation) try one way classification model) 신뢰집합(1등※승 confidence set) 치환(3 n) 정칙행렬(nons ingular matrix) 정 다변량 정규분포(FER) 3분부 TAt nonsingular multivariate normal distris 다변량 정규분포(3로 FRAm multivariate norr onse variable) 계수(#1: rank) 회귀계수(DS6%: regression coefficient) 표본회귀계수(sample regression cn (Baa Characteristic value) 선형회귀모형(월)미로 linear regression model) 설명변수(explanatory variable 순(Twt simple) 평균오차제곱합(주119※제곱합 mean squared error sum of squares) 중심극한정리(+L 칙(☆법의 굿 law of large numbers) 표본적률(sample moment) 분위수(A)(1 quantile) 표본분이 ral limit theorem) 극한분포(138Am limiting distribution) 점근분포(Wif ft asymptotic distribution 6 번 sample quantile) 슬럿츠키(Slutsky) 근(mit asymptotic) 첨예도 (4815 kurtosis) 표본상 나 브사아저요하(수봐도
