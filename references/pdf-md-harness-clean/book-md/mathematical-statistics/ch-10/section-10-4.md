# 10.4 회귀분석

> OCR engine: macOS Vision (`ko-KR,en-US`)
> Original PDF pages: 417-432

<!-- page 417 -->

회귀분석

변수 사이의 함수관계 조사를 할 때 가장 기본적으로 사용되는 모형으로서 다음의 선형회귀정규분포모형은 4장에서 소개되었다.

<!-- page 418 -->

Yi=toBo+aill too+ tipb, ter e,~N(0,02), i= 1,,n (Bo,3,,,3,는 실수, 0.20 이러한 선형회귀정규분포모형을 벡터와 행렬을 사용하여 나타내기 위하여 loall tip e

## Y

Lino inl tmp 8, 라고 하고, 설명변수의 행렬인 nX(p+1)행렬 X는 설명변수의 주어진 값의 행렬로 서 계수가 (p+ 1)인 것으로 가정하면 선형회귀정규분포모형을 다음과 같이 나타낼 수 있다. (Y= xste re~ N,, (0,02T) BERP+1, 02> 0, rank(X)=20+1 이러한 선형회귀정규분포모형에서 회귀계수의 최대가능도 추정량과 최소제곱 추정량 은 일치하는 것으로서 그 표본분포는 이미 4장과 6장에서 소개되었으며 이를 정리하 면 다음과 같다. 정리 10.4.1 선형회귀정규분포모형에서의 추정량과 표본분포 (a) 회귀계수의 선형결합 cB와 o2의 전역최소분산불편 추정량은 다음과 같이 주 어진다. cp=c(rix) lxty 8= ly- 23121(m-p-1)=(Y-X3)'(Y-X3)/(n-p-1) (6) B=(XX)-'X'Y~N,+1(3,02(MX) 1) (c) 3와 2은 서로 독립이다. (a) (n-p-1)0792~ x2(n-p-1) [증명] 이 경우에 Y의 확률밀도함수는 0=(3',02)'E RP+1X (0,∞0)를 모수로 하여 =expl-yg/(202)+3X3/02-BXXg/(202)-n[10g(2702)1/2} 434 10장 분산분석과 회귀분석

<!-- page 419 -->

와 같이 나타내어지고 <정리 8.3.2>의 조건을 만족시키는 지수족의 경우이다. 따라서 (X'y, Y'Y카 0=(3,02)'ERD+1X(0,∞)에 관한 완비충분통계 량이다. 그런데 ry=(Xx)B,riy=(0-0-1)8+8(261)3 이므로 (B,o2)은 (X'Y, Y'Y)의 일대일 함수로서 이 역시 0에 관한 완 비충분통계량이다. 한편 정리 6.5.2>로부터 28과 7은 각각 dB와 02의 불편추정량이다. 따라서 완비충분통계량의 함수인 c'B과 0은 각각 2'B와 02의 전역최소분 산불편 추정량이다. 표본분포에 관한 (b), (c), (d)의 증명은 <정리 4.4.62에 주어져 있다. <정리 10.4.1>의 표본분포를 이용하여 회귀계수 3의 선형결합에 대한 신뢰집합과 동시신뢰구간을 <정리 10.1.3>에서와 같은 방법으로 구할 수 있으며 이를 정리하면 다 음과 같다. 정리 10.4.2 선형회귀정규분포모형에서의 신뢰집합과 동시신뢰구간 계수가 7인 (p+1)×r 행렬 C에 대하여 C의 열벡터공간을 col(C) = { Ca : aE R"로 나타내면 선형회귀정규분포모형에서 다음이 성립한다.

## (a) Ps:(C'B-C'B)'(C(XX)-'C)-'(C'B-CB)

5roFa(r;n-p-1)}=1-0 (o) Panleg-dals ve(xx)-eo vnra(77-p-1), cEco(C) = 1-a 선형회귀모형에서는 회귀계수 전체의 유의성보다는 일부의 유의성에 대한 판단을 필 요로 하는 경우가 많이 있다. <예 6.5.1~에서와 같이 210= 1(i= 1,,7)인 경우에는 B(Y:co:tiam)=Bo+Bizat:+B,lin (i= 1,,n)

## 로서 절편 B,을 제외한 회귀계수 (B,,•·,B,)의 유의성이 관심의 대상이다. 이러한

회귀계수 일부의 유의성에 대한 가설 검정을 다음과 같이 할 수 있다.

<!-- page 420 -->

정리 10.4.3 선형회귀정규분포모형에서의 회귀계수의 유의성 검정 선형회귀정규분포모형 Y=HoBothipite e~N,, (0,01)

## BER", B,ER"0220

(rank(Xo.si)= Potpi, rank(Xo)=po: rank(Xi)= P1 을 가정할 때, 일부 회귀계수의 유의성에 대한 가설 1o: 81=0 vs 11: 51=0 의 최대가능도비 검정에 대하여 다음이 성립한다. (a) 10=Xo(X620) X6, 2io=(1-D)X,, Mo= Xio(xioxio)- Xio라 고 하면

## BERA

min IIY-Xo3612= min IIY-Xo8o-X8,12+851103 (6) P(110)=Y'TLoY, SSE=Y'(1-Io-11o)Y 라고 하면 검정통계량은 Fin=

## R(110)/P1

SSE/(n-po-P1) 이고 크기 a(0<a< 1)인 기각역은 다음과 같이 주어진다. "F,≥ Fa(p;2-P0-P1)” (c) 검정통계량에 대하여 다음이 성립하고, 검정력 함수는 6의 증가함수이다. F,= SSE/(2-70-D) ~F(0:7-70-7:6), 6=81317.02.8./02 R(110)/p1 [증명] 이 경우에 X=(Xo,K,), Io.1= X(X'X)-T, In= Xo(XS Xo) 1X6 라고 하면 Io.1: Io: 1710는 모두 정사영행렬이고 다음이 성립하는 것을 <정리 6.5.3>에서 알고 있다. Ho.1= 1o+ 11o: 161110= 0 따라서 I-Io= (I-Io,1)+ 110 이고, (a)가 성립하는 것은 다음으로부터 명백하다. 436 10장 분산분석과 회귀분석

<!-- page 421 -->

BE Rhu min IIY-Xo36 12=y'(1-II)Y

## BnERRB,ER"

min IIY-X03.- X,8,12=Y'(1-Io.1)Y 한편, 이 경우에 로그가능도는 1(0) =- 그 202 19-2680-2,8, 12- 7 108(3702) 이므로, 02에 대한 전체 모수공간과 귀무가설하에서의 최대가능도 추정량은 다음과 같다.

## BER",B,ER"

minIIY-Xo8o-X,8, 12/n=SSE/n %% = min IIY-50Bo 112/n=(SSE+Y'DloY)/m

## BER"

: 20600-100)=710816)=721021+170) 따라서 검정통계량은 Fn으로 주어지고 기각역은 F,의 큰 값으로 주어진다.

## 한편 II10가 멱등행렬이고

trace(To)= trace(xio(xioxi)-'x10h=tracef(xioxi)-'xiorio)=p1 이므로, 정리 10.3.2>로부터 다음이 성립하는 것을 알 수 있다. R(10)/02=Y'110282x2(06), 8=(20Bo+818,)010(5080+X8.)102 그런데 IioXo = 0이므로 8= 8ix| 110X13/02 또한 같은 방법으로 SSE/2=y'(I-Do.1)Y/02~x'(n-po-p) 임을 알 수 있고, 1lo(1-Io.1)= Iio(I-Io-110)=0 이므로 R(110)=Y'D1oY와 SSE=y'(I-Io-I1o)Y 가 서로 독립이다. 따라서 일반적으로 5F,=-

## SSE/(7-00-p) ~F(P:7-Po-7;6)

R(110)/ p1

<!-- page 422 -->

이다. 한편 귀무가설 Ho : 3, = 0하에서는 8= 8:2110218182=0 이므로 크기 0(0< 0< 1)인 기각역은 (b)에서와 같이 "F,≥Fa(p,n-D0-P)” 로 주어진다. 또한 <예 10.3.12과 같은 방법으로 이 검정의 검정력 함수가 0의 증가함수 인 것을 밝힐 수 있다. 정리 10.4.4 회귀계수의 선형결합에 대한 유의성 검정 선형회귀정규분포모형 1Y= xBte BERP+1, 02≥ 0, rank(X)= p+1 e~ N,, (0,021) 을 가정할 때, 계수가 7인 7X (p+1) 행렬 C'에 대하여 가설 H:CB=OUs H:C'BKO 의 최대가능도비 검정에 대하여 다음이 성립한다. (a) II10=X(XX)-'C(C(XX)-C)-C(rX)-X, B=(Xx)-1Xly 라고 하면 BER,Cg=O|| Y - X3 M 2 = min Y'TY/°=(CB)[Var(CB)-'(¢③) (6) 21.0=X(X'X)-'X', SSB=Y (-IIO)Y, R(10)=Y'D10Y라고 하 면 검정통계량은 F,,=

## R(10)/

SSE/(n-p-1) 이고 크기 a(0< a< 1)인 기각역은 다음과 같이 주어진다. "F,≥Fa(7,7-p-1)” (c) 검정통계량에 대하여 다음이 성립하고, 검정력 함수는 6의 증가함수이다. F;,,= SSE/(n-p-1)~P(n-p-16), 6=BCIC(rx)-IC1-1C3/02 R(10)/r 438 10장 분산분석과 회귀분석

<!-- page 423 -->

[증명] 증명의 핵심은 이 정리에서의 가설 검정을 <정리 10.4.3>의 가설 검정으로 대응하여 인지하는 것이다. 이러한 대응을 이해하기 위하여, 행렬 C 의 열벡 터공간의 정규직교기저(TE※☆EI, orthonormal basis) 벡터를 열로 갖는 (p+1)×> 행렬을 C이라고 하고 이를 확장하여 RP+1의 정규직교기저 벡 터를 열로 갖는 (p+1)×(p+1) 행렬을 (Co C.)이라고 하자. 즉 CC=+i-r CG=1,, CiCi=0 이고 C= C,B인 정칙행렬 B가 존재한다. 이로부터 (XB=X(CoG)(CG)'B=Do%o+DMi rank(Do)=p+1-r, rank(D)=1, rank(Do;Di)=p+1 Do=xCo, D,=IG, 70=C6B, M= C'B 와 같이 <정리 10.4.3>의 선형회귀모형에 대응하도록 모형을 나타낼 수 있다. 또한 CB=06BCB=06CB=0611=0

## TE RPHI-T

IIY-Do7o 112 이므로, 정리 10.4.3>의 (a)로부터 행렬 (Do D,)의 열벡터공간 col((Do.D)={Do+Dn:NERMI-,NER} 에서 행렬 D,의 열벡터공간의 직교여공간(GxW, orthogonal complement) col(Dio)= (aEcol((Do,D,) : a' Do= 0

## 으로의 정사영행렬을 II라고 하면 다음이 성립하는 것을 알고 있다.

BE RP+,¢'3= 0 min IIY-X3 II2=

## TE RPHITTER

min

## IIY-D070-Dn12+YINoY

한편 (Do Di) = X(C, Ci) 이므로 col((Do.D)=(X(Cono+Cn): NERP+L,TERS =(XB : BE RP+1」=col(X) 임을 알 수 있고, 행렬 D의 열벡터공간의 직교여공간 col(Dio) 이 행렬 S=X(XX)- IC 의 열벡터공간임을 다음으로부터 알 수 있다.

<!-- page 424 -->

col(Do)= (aEcol((Do.D) : dDo=01 =(aEcol(X) : dXC= 01 ={XB: BX'XC= 01 ={x3: r'xgE col(C)} ={x(XX) ICE : fER'} =col(X(rCx)- IC) 따라서 행렬 D,의 열벡터공간의 직교여공간 col(Dio) 으로의 정사영행렬이 II10=S(SS) S"=X(XX)-'C(C(XX)-'C) C(XX) X0 로 주어지고, (a)가 성립하는 것을 알 수 있다. 또한 <정리 10.4.3>에서와 같 은 방법으로 (b), (c)가 성립하는 것은 명백하다. 지금까지의 선형회귀모형과는 다르게 Y=XB+e, C3=0 e~N,,(0,0:l)

## IBERD+!

Tank(X)=D+1-7<p+l,rank(C)=r 02≥0,

## X, C의 행들은 선형적으로 독립

## 와 같이 설명변수의 행렬 X의 열들이 선형적으로 종속이고 제약조건

C'B=0 이 추가된 꼴로 주어지는 모형을 생각할 수 있다. 이러한 모형을 선형모형([*페, linear model)이라고 하며, 이는 일원분류모형이나 이원분류모형 등의 분산분석 모형 이나 선형회귀모형을 모두 포괄하는 모형이다. 예 10.4.1 선형모형으로서의 일원분류정규분포모형 일원분류정규분포모형 Ki=u+aitesj ,7,0:= 0 ej~N(0,0), i=1,,k; j= 1,,74 8<EK+8,-8<&<+∞(i=1,18), 0:>0 에서 440 10장 분산분석과 회귀분석

<!-- page 425 -->

그m, 2m 0. 0 X= 1ng 0 ln •• : ,B=(W,a1ax), c'=(0,71,,%) 라고 하면, 이 모형을 다음과 같이 나타낼 수 있다. [¥= 88+e,¢8=0 1n, 1n1 ... , X= 1m2 0 1m2 : : : 0 . 1m 이러한 모형의 표현에서 행렬 X를 일원분류모형의 설계행렬(☆+4731, design matrix)이라고 부른다. 이러한 설계행렬의 경우에 rank(X)= KC k+1 이지만 3에 대한 제약조건 c'= 0이 추가되어 모수 3에 의한 모형의 식별이 가능한 것이다. 이 경우에 행렬 X*X가 정칙행렬이 아니므로 그 역행렬을 생각 할 수 없게 되고, 정사영행렬들의 표현이 다르게 주어지지만 개념적으로는 <정 리 10.4.4>에서와 같은 방법으로 모수의 추정이나 검정에 관한 이론이 전개될 수 있다.

<!-- page 426 -->

일원문듀모형 다변량 정규분포 신뢰십합 지환 연수 계수 회귀계수 고유값 선형회귀모형 정칙행렬 정칙 다변량 정규분포 확듈석문변환 중심극한정리 표본회귀계수 설명변수 츠키 점근 대수의 법칙 표본적률 극한분포 단순 평균 난수 첨예도 균등난수 표본상관계수 분위수 분산안정변환 표본분위수 점근분포 1대가능도 추정법 추정 추정량 본데칼로적분 다중모수 지수족 점수함수 연습문제 가능도방정식 일치성 가능도 함수 적률이용주정량 쿨백-라이블러 괴리도 순오목함수 의 공간 확률측도 정사영 조건부화률 공리 최소제곱 추정법 확률 최소제곱 추정량 점근정규 표본공간 확률밀도함수 랜덤한 실험 확률변수 사전 사후 독립 가산가법 지포함수 평규 기댓값 연속형 이산형 표주편차 이상 확률분포 화률질량합수 표주화

## 10.1 어떤 화학약품의 합성 공정에서 반응온도에 따른 수율의 비교를 하기 위하

여 온도 80°C, 90°C, 100°C, 110°C에서 랜덤하게 실험을 행한 결과 다음과 같은 자료를 얻었다.

## 80°C

반응온도에 따른 수율 90.2

## 90°C

90.0 89.8

## 100°C

89.5 90.8 90.5 91.4 91.6

## 110°C

90.8 91.3 91.2 90.3 90.4 이 자료에 다음 일원분류정규분포모형을 가정하고 답하여라. Kis= Niteij Ci~N(0,0), i=1,0,4; j=1,…,74 iid -8<B<+8(i=1,,K), 02>0 (a) 반응온도라는 인자의 유의성에 대한 가설 10: M1=…=M4 US H:M1,…씨가 모두 같지는 않다. 을 최대가능도비 검정법에 의해 유의수준 a= 0.05의 검정을 하여라. (b) 각 반응온도에 따른 평균 수율의 비교를 위한 쉐페의 동시신뢰구간을 신 뢰수준 0.90에서 구하여라. (c) (b)에서 신뢰수준 0.90의 동시신뢰구간을 본페로니의 방법으로 구하여라. (d) (b)에서의 방법이 (C)에서의 방법에 비해 갖는 장점을 예를 통하여 설명하 여라.

## 10.2 일원분류정규분포모형

Aij= Mitei) e:~N(0,02), i=1,,k; j= 1,…,76 -8<KiK+8(i=1,,&) 에서 분산 o2이 알려져 있다고 가정할 때, 가설 442 10장 분산분석과 회귀분석

<!-- page 427 -->

16 : 11=…= Nx US H, : M1, A가 모두 같지는 않다. 에 대하여 크기 0(0< a< 1)인 최대가능도비 검정의 기각역을 구하여라.

## 10.3 여러 개의 이항분포를 비교하는 경우로서

1i.n,~B(7.p:) (i=1,,k) 이고 Xin(i= 1,,k)들이 서로 독립인 경우를 생각해보자. 표본크기 7,가 충분히 클 때의 분산안정변환인 와 같은 근사와 연습문제 (10.2)를 이용하여 다음 가설을 유의수준 a(0<&<1)에서 근사적으로 검정하는 방법을 제안하여라. Ho : PL =…= Pr US H, : P,P가 모두 같지는 않다.

## 10.4 어떤 제품의 중합반응에서 약품의 흡수속도(g/hr)는 촉매량(A)과 반응온도

## (°C)(B)에 따라 달라진다고 생각된다. 촉매량의 네 가지 수준과 반응온도의

세 가지 수준에서 흡수속도를 관측한 결과 다음과 같은 자료를 얻었다. 약품의 흡수속도

## B, (110)

## B,(120)

## B,(130)

## A,(0.2)

87, 94,96 108, 99, 101 111, 116, 115 4,(0.4) 95, 98, 101 110, 114, 118 126, 121, 127 4(0.6) 99, 100, 107 112, 117, 115 127, 125, 131

## A,(0.8)

91, 98, 104 109, 103, 107 120, 116, 122 이 자료에 다음 이원분류정규분포모형을 가정하고 답하여라. 스카= W.taitB; tNisteik 20;=0, 27= 0(j= 1,:,3), j=1 27= 0(i= 1,,4) Cix~N(0,02), i= 1,4; j= 1,3; k= 1,,3 (A., a.B,,%;는 실수이고 02≥0 (a) 촉매량(A)과 반응온도(B)의 교호작용효과의 유의성에 대한 가설 H60: 20= 0 2S H1D:%(i= 1,0; j= 1,6)가 모두 0은 아니다.

<!-- page 428 -->

를 최대가능도비 검정법에 의해 유의수준 a= 0.05에서 검정을 하여라. (b) 촉매량에 따른 평균 흡수속도의 비교를 위한 쉐페의 동시신뢰구간을 신로 수준 0.90에서 구하여라. (C) (b)에서 신뢰수준 0.90의 동시신뢰구간을 본페로니의 방법으로 구하여라.

## 10.5 교호작용효과가 없는 균형된 이원분류정규분포모형

Bik=W.taitB,teijk 5i=1 La,=0. 28,=0. CS~N(0,02), i=1,0; j= 1,6; k=1,7 K.;0;3,는 실수이고 02> 0 에서 다음에 답하여라. (a) A.., an, B,, o의 전역최소분산불편 추정량을 구하여라. (b) 4인자 효과의 유의성에 대한 가설 16: a1 ==0.=0 Us Ed: a(t=1,,a)가 모두 0은 아니다. 에 대하여 크기 a(0< a< 1)인 최대가능도비 검정의 기각역을 구하여라. (C) (b)에서의 검정통계량의 분포를 구하여라.

## 10.6 X~N(,1)일 때, Ao, A,이 대칭행렬로서 멱등행렬이고

40=1,+A2, 2'422≥ 0, V2 이면, X'A2X~x (86), r2=trace(42), 02=W42이고 4,42= 0임을

## 밝혀라.(참고: 부록 II '정사영의 직교분해 )

## 10.7 회귀모형으로서 다음과 같은 모형을 가정하고 아래에 답하여라.

(Yij=ctditeij eu~N(0,02), i= 1,,0; j=1,6 iid Ic,d는 실수, o2>0 444 10장 분산분석과 회귀분석

<!-- page 429 -->

(a) 위의 모형을 적절한 벡터를 사용하여 다음과 같이 나타낼 수 있음을 밝혀라. Y=dozo+ds te, toz1=0 1e~N,,(0,021), n=ab (do,d는 실수, 02> 0 (b) 회귀모형의 유의성에 대한 가설 Ho:d=o vs H:d*0 에 대하여 크기 a(0< a< 1)인 최대가능도비 검정의 기각역을 구하여라. (c) (b)에서의 검정통계량의 분포를 구하여라.

## 10.8 회귀모형으로서 다음과 같은 모형을 가정하고 아래에 답하여라.

NY=B,+3,2,ter 2i,,2k는 주어진 수이고 모두 같지는 않다. e;~N(0,02/u), i=1,,k; er,,e는 서로 독립 Bo,3은 실수, 0'>0; 2≥ 0는 주어진 수 (a) 이러한 모형에서 Bg: 3,의 최대가능도 추정량은 가중 제곱합 i= 1 12136-(36+312:)}2 을 최소로 하는 가중최소제곱추정량(토) 제곱METh, weighted least squares estimator)으로 주어지는 것을 밝혀라. (b) 이러한 모형에서 회귀모형의 유의성에 대한 가설 10: 31=0 vs H,: 3, =0 에 대하여 크기 a(0<e< 1)인 최대가능도비 검정의 기각역을 구하여라. (c) (b)에서의 검정통계량의 분포를 구하여라.

## 10.9 로지스틱회귀모형이라고 불리우는 다음과 같은 모형을 가정하고 아래에 답

하여라. (Y;~B(Pp), i=1,,k; Y1,, YA는 서로 독립 5log 1- Pi = B,+ B,2;, 21,,0%는 주어진 수이고 모두 같지는 않다. (Bo, 3은 실수

<!-- page 430 -->

(a) 가능도방정식은 M(8:-77)=0 로 주어지고, 가능도방정식의 근이 있다면 그 근이 최대가능도 추정값이 되 는 것을 밝혀라. (b) 표본크기 n,(i=1,,k)들이 충분히 클 때, 최대가능도 추정량의 일단계 반복법에 의한 근사 추정값을 다음의 반복가중최소제곱법으로 구할 수 있는 것을 설명하여라. (0단계) p:=Y:/n, w,0)=np(1-p), 210)=108

## 1- P:

^ (x단계) (r= 1,2,…·) Bi - D;Pi 6, (1-77)

## 10.10 로그선형회귀모형이라고 불리우는 다음과 같은 모형을 가정하고 아래에

답하여라. 〈10g(1;)= 3,+ 3,a;, 21,…,2k는 주어진 수이고 모두 같지는 않다. KiPoisson(A).j=1,7;2=1,,k;A,>0,Yu는 서로 독립 LBo:3,은 실수 (a) 36•=Jil ++Ymn(i= 1,,k)라고 할 때 가능도 방정식은 5(0.-72)=0 (10g1;= Bo+ B,2:) 22:(8:.-ma)=0 로 주어지고, 가능도 방정식의 근이 있다면 그 근이 최대가능도 추정값이 되 는 것을 밝혀라. 446 10장 분산분석과 회귀분석

<!-- page 431 -->

(6) 표본 크기 Dp(i= 1,…,k)들이 충분히 클 때, 가능도방정식의 일단계 근사 해가 다음과 같이 주어지는 것을 설명하여라 여기에서 80=(60,60), X=(1,2), 1=(1,…,1), 2= (31,0k)', Eo = diag (009), 20) =71일) _ (i=1,,k) 이고, 어깨 글자 (0)는 초기값을 나타낸다.

<!-- page 432 -->

riment) 확률변수 (1주평 obability density function random variable) 연속형 로 화포인 continuous type) 이상(목t improper) 확률분포(8835) 7 probability distribution) 지표함수(1음황 이산형 (3h ciscrete type) 확률질량함수(1월 3w 2 009 probability mass fuction) 확률밀도함수(1) 8주 189 cumulative distribution function) 표준지수분포(1) standard exponential distribution) 급수(월) power series) 확률생 function) 평균(45key mean) 기댓값(수값 expected value) 표준편차(1부 1※ standard deviation) 표준화 (131t standardized) 누적분포함수 7소RE probability generating function) 적률생성함수(RESik gres moment generating function) 적률(참% moment) 누율생성하 19d cumulant generating function) 누율(## cumulant) 이변량(bivariate) 확률벡터(random vector) 반복적분(iterated integra 적률생성함수(joint moment generating function) 결합누율생성함수(joint cumulant generating function) 합누율 (joint c oint) 주변(Fls marginal) 공분산(#A covariance) 상관계수(NBS correlation coefficient) 결합적률(#금)부 joint mon lal variance) 회귀함수 조건부(1FfW conditional) 조건부평균 (BB19 regression function) 평균제곱예측오차(mean squared prediction error) 행벡 conditional mean) 조건부기댓값(conditional expected value) 조건부분산 vector) 전치(transpose) 평균벡터(mean vector) ative definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(R41 popul 분산공분산행렬(variance covariance matrix) 정부호 순랜덤추출(₩\랜덤HH simple random sampling) 랜덤표본(random samp 집단분포(토#14 f population distribution) 비복원추출(sampling without replace pution) 복원추출(1) Mul sampling with replacement) 이항분 (BHP population proportion) 초기하분포(12% al th f hypergeome t binomial distribution) 대의적 정의(ftat 교 repr

## 7) 다항계수(8168 multinomial coefficie

nal definition 다항분포(STAm multinomial di

## E (12)

1포(#)(iA t geometric distribution) tion) 음이항전개식(negative 1A f negative binomia expansion) 포아송(Poiss) 속 과정(Poisson process) :currence rate) 정상성 rement) 비례성(propc ity) 독립증분성(indepe ential distribution) 감마분 회귀성(rareness) 지수분 베이지안 추론 je parameter) 척도모수(RIA) 930 a distribution) 형상모수(HSWA 1ormal distribution) 분위수(upper quanti ameter) 표준정규분포(1: 44 TERA715 S 본비율(MA Htw sample proportion) 표본평균(*TH) 간(Bg2ml parameter space) 통계량(StBtm sta statistics) 표본중앙값(1:+값 sample medi an) 표본분포(4) f) ean) 표본분산(IT) sarnple variance) 순서통계량(JEFT W 3r) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(1)+ ffi uniform distribur distribution) 위치모수(htTE to location parameter) 척도모수(RIB 6w scale 분포 부포(chi-squared distribution) (=9491 triangular distribution) 야코비안(Jacobian) 자유도(htt)) 신뢰수준(1)ks confidence level) 신뢰구간 degreas of freedon. 분류모형 one way classification model) 신뢰집합(1매 confidence set) 치환(1)R per 06ml confidence 적분변환 (1주 on) 정칙행렬 (비값 characteristic value) 선형회귀모형(NE94페 Ingular matrix) probability integral transtormation) 다변량 정규분포(※청w FRAth multivariate no

## 정칙 다변량 정규분포(TEM

linear regression model) 설명변수(explanatory variable) 반응변수 8분은 FtAt nonsingular multivariate normal distn 곱합(7:※제곱합 mean squared error sum of squares) 중심극한정리(Phi AE 9T central limit theorem) 극한분포(AR5) 7F limitir able) 계수(3189 rank) 회귀계수(미% regression coefficient) 표본회귀계수(sample regression coefficient) 단순(Th simple) c 표본분위수(wAS 118 sample quantile) 슬럿츠키(Slutsky) 점근(Wir asymptotic) 첨예도(4398 kurtosis) 표본상관계수(ABA1 sample on) 점근분포(#Eati asymptotic distribution) 대수의 법칙(X의 표 law of large numbers) 표본적률(sample moment) 분위수(A) 15) 8) 몬테칼로적분(Monte Carlo integration) 적률이용추정량(15※NIFIF method of moments estimator(MME)) 추정 (Htt estimation) 추정량 (1E) in coefficient) 분산안정변환(AWs variance syabilizing transiormation) 난수(Rl,w random number) 균등난수(1)%ml uniform randon itor) 일치성 (-t consistency) 가능도 함수(THER Bw likelihood function) 우도(XR) 최대가능도 추정법(XDAt) 1)it maximum likelihood c

1) 가능도방정식(THE 폴it Iikekihood equation) 순오목함수(strictly concave function) 경계(19f boundary) 다중모수 지수족(31 )) 18hk multi

맹(a information number) 최소제곱 추정법(least squares estimation) 최소제곱 추정량(least squares estimator) 열벡터 공간(column space) 정사영(iE) exponential family of pdfs) 쿨백-라이블러 괴리도(Kulback-Leibler divergence) 점근정규성 (WiT IE tH asymptotic normality) 점수함수(score functic sure) 조건부확률(1:4 W pR conditional probability) 사전(mi prior) 사후(Tt posterior) 독립(3h mutually independent) 종속(6E mutually depende ndicular projection) 공리(소T axiom) 표본공간(Ex 2ml sample space) 확률(mf probability) 가산가법성(countable additivity) 확률측도 (H3JMSt prob: 실험(random experiment) 확률변수(18) 59y random variable) 이산형(1xl discrete type) 확률질량함수(6.9 . me a l probabillity mass fuction) 률밀도 unction) 평균(주소 mean) 기댓값(비값 13w probability density function) 연속형(1% continuous type) 이상(월1 improper) 확률분포(P: expected value) 표준편차(#유권 standard deviation) 표준화(lf: standardized) 누적분포함수(분#417%) (wAti probabillity distribution) 지표함수(J) 92 nction) 적률생성함수(제84kwh moment generating function) 적률(1w moment) 누율생성함수(및%HtBiwy cumulant generating function) 누율 (목 stribution function) 표준지수분포(1) awAt standard exponential distribution) 멱급수(표: power series) 확률생성함수(#4ntill probability ge t) 이변량(bivariate) 확률벡터(random ve on coefficient) 결합적률(ww joint moment) 결합적률생성함수(joint moment generating function) 결합누율생성함수(joint cumulant generating ur 반복적분 iterated integral) 결합(1a joint) 주변(Blift marginal) 공분산(144): covariance) 상관계수(AEBS 6S) BStagy regression function) 평균제곱예측오차 mean squared prediction error) 행벡터(column vector) 전치(transpose) 평균벡터(mean vector) 분산 율(joint cumulant) 조건부(19) H conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산(conditional variand variance covariance matrix) 정부호(nonnegative definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(B4.m population) 모집단 비율(htte population proportion) 초기하분포(18ahh hypergeometric distribution) 복원추출(1 jittwi sampling with replacement) 이항분포 3t population distribution) 비복원추출(sampling without replacement) 단순랜덤추출(매원랜덤httt simple random sampling) 랜덤표본(random ient) 기하분포(※h Ti geometric distribution) 음이항분포(14) nomial distribution) 대의적 정의(ften Th representational definition 다항분포(31941 multinomial distribution) 다항계수(3TEG 9x mmultind (Poisson) 포아송 과정(Poisson process) 발생률(occurrence rate) 정상성(stationarity) 독립증분성(independent increment) 비례성(proportiona -TEAt negative binomial distribution) 음이항전개식(negative binomial expan : 정규분포(11 TERA) fl standard normal reness) 지수분포(exponential distribution) 감마분포(gamma distribution) 형상모수(HEWXkl shape parameter) 척도모수(FIE f g scale pe Atti sample proportion) 표본평균(풋☆주K) distribution) 분위수(upper quantile) 모수공간(19:4m parameter space) 통계량(8cnt s statisti 초다빗가 sample medi an) 표본분포(#AA fi sampling distribution) 위치모수(11mfgh location parameter) 척도모수(PE ) 평 sample mean) 표본분산(AW sample variance) 순서통계량(M)Fttatm order statistin er) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(1)¥Am uniform distribution) 삼각분포(=.RAm triangular distributic cobian) 자유도(Emit degrees of freedom) 카이제곱분포(chi-squared distribution) 신뢰수준(1등※가* confidence level) 신뢰:1 on) 확률적분변환(Ht 후 1R AT confidence interval) 일원분류모형 probabillty integral transformation) 다변량 정규분포(33월 m TER9) 7F multivariate nor T one way classification model) 신뢰집합(1301승 confidence set) 치환 (BA값 characteristic value) 선형회귀모형(※미와 linear regression model) 설명변수(explanatory variable n) 정칙행렬(nons ingular matrix) 정칙 다변량 정규분포(TE ※ m FiA th nonsingular multivariate normal distr 순(88t simple) 평균오차제곱합(주보훈제곱합 mean squared error sum of squares) 중심극한정리(P) onse variable) 계수(동 18 rank) 회귀계수(Bgf%ws regression coefficient) 표본회귀계수(sample regression cr ral limit theorem) 극한분포(NR477 limiting distribution) 점근분포(Wifrtn asymptotic distribution 11w sample quantile) 슬럿츠키(Slutsky) 점근(Mfli asymptotic) 첨예도(47s kurtosis) 표본상 칙(*번의 Rl law of large numbers) 표본적률(sample moment) 분위수(Att quantile) 표본분으
